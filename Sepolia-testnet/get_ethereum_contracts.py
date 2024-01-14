from config import *
import sys, re, requests, json, os, shutil, subprocess
from bs4 import BeautifulSoup, NavigableString
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC



api_key = 'RYABP4DKZF4CTXDAXWRSRYM6NKB85TUWMM'
broswer_url = 'sepolia.etherscan.io'

def import_replace(matched):
    return "import \"./" + os.path.basename(matched.group('filename')) + "\"";


def pre_check():
    global contract_address

    if (len(sys.argv) != 2):
        sys.exit(bcolors.FAIL + "Usage: need exactly 2 parameters, <URL>" + bcolors.ENDC)

    res = re.findall(r'.*([0-9a-zA-Z]{40}).*', sys.argv[1])

    if (len(res) != 1):
        sys.exit(bcolors.FAIL + "Confused about given URL or address" + bcolors.ENDC)

    contract_address = "0x" + res[0]
    print(contract_address)

def get_sourcecode():
    global contract_address

    while True:
        print( "Searching solidity code of address:", bcolors.OKGREEN , contract_address, bcolors.ENDC)
        res = requests.get('https://api-{}/api?module=contract&action=getsourcecode&address={}&apikey={}'.format(broswer_url, contract_address, api_key)).json()
        contract_name = res['result'][0]['ContractName']

        if contract_name == 'Diamond':
            sys.exit(bcolors.FAIL + f"Diamond proxy contract pattern: https://{broswer_url}/address/{contract_address}#code. Please check it manually." + bcolors.ENDC)
        
        if contract_name in ['UpgradeableProxy', 'TransparentUpgradeableProxy', 'AdminUpgradeabilityProxy', 'BeaconProxy']:
            c = input(f"This contract seems like a proxy contract, {bcolors.WARNING}find its implementation{bcolors.ENDC} or not?({bcolors.WARNING}Y{bcolors.ENDC}/n)")
            if c != 'n':
                slot = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50" if contract_name in ['BeaconProxy'] else "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
                payload = {"jsonrpc":"2.0", "method": "eth_getStorageAt", "params": [contract_address, slot, "latest"], "id": 1}
                logic_address = "0x" + requests.post('https://rpc.flashbots.net', json = payload).json()['result'][-40:]
                contract_address = logic_address
                print( "Found logic contract address:", bcolors.OKGREEN , contract_address, bcolors.ENDC)
                if contract_name in ['BeaconProxy']:
                    sys.exit(bcolors.FAIL + f"Beacon proxy contract pattern: https://{broswer_url}/address/{contract_address}#code. Please check it manually." + bcolors.ENDC)
                continue
        break

    return res

def get_bytecode():
    global contract_address

    url = f"https://{broswer_url}/address/{contract_address}#code"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"}

    # Send an HTTP GET request to the URL with the user-agent header
    response = requests.get(url, headers=headers)

    bytecode = ''

    # Check if the request was successful (status code 200)
    if response.status_code == 200:
        # Parse the HTML content with BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find the div with id "verifiedbytecode2"
        verified_bytecode_div = soup.find('div', {'id': 'verifiedbytecode2'})
        
        # Print the content of the div
        if verified_bytecode_div:
            bytecode = verified_bytecode_div.text
        else:
            print("Div with id 'verifiedbytecode2' not found on the page.")
    else:
        print(f"Failed to retrieve the page. Status code: {response.status_code}")
    
    return bytecode

def get_opcode():
    global contract_address
    
    driver = webdriver.Firefox()
    url = f"https://{broswer_url}/address/{contract_address}#code"
    driver.get(url)

    try:
        element = driver.find_element(By.ID, 'btnConvert3')
        driver.execute_script("arguments[0].click();", element)

        
        data = driver.page_source
    finally:
        driver.quit()

    soup = BeautifulSoup(data, 'html.parser')

    # Find the div with id "verifiedbytecode2"
    verified_bytecode_div = soup.find('div', {'id': 'verifiedbytecode2'})

    opcode_list = verified_bytecode_div.contents[::2]

    # Now, 'strings' is a list containing all the strings between <br/> tags
    opcode = '\n'.join(opcode_list)

    return opcode

def create_directory(directory):
    print("Creating directory:", bcolors.OKBLUE, directory, bcolors.ENDC)
    while os.path.exists(directory):
        c = input(f"source file direct already exists, replace it, save as another name or {bcolors.WARNING}cancel{bcolors.ENDC}?(r/s/{bcolors.WARNING}C{bcolors.ENDC})")
        if c == 'r':
            shutil.rmtree(directory)
        elif c == 's':
            directory = directory + "_1"
            print("Creating directory:", bcolors.OKBLUE, directory, bcolors.ENDC)
        else:
            sys.exit(bcolors.FAIL + "cancel" + bcolors.ENDC)
    os.makedirs(directory)


def write_srcfiles(codes, contract_name, base_dir):
    if (codes[0] == '{'):
        if codes[1] == '{':
            codes = json.loads(codes[1:-1])['sources']
        else:
            codes = json.loads(codes)

        for i in codes:
            raw_code = codes[i]['content']
            data = re.sub(r".*import.*['\"](?P<filename>.*\.sol)['\"]", import_replace, raw_code)

            filename = os.path.join(base_dir, os.path.basename(i))
            print("Writing file:", bcolors.OKBLUE, filename, bcolors.ENDC)
            with open(filename, "w") as f:
                f.write(data)
    else:
        each_files = re.findall(r"\/\/ File ([\s\S]*?\.sol)(?:.*)([\s\S]*?)(?=\/\/ File|$)", codes)
        each_parts = re.findall(r"pragma\s+solidity([\s\S]*?)(?=\/\/ File|$)", codes)


        if len(each_files) != len(each_parts):
            print(bcolors.FAIL + "Something error, writing as single file" + bcolors.ENDC)
        if len(each_files) == 0 or len(each_files) != len(each_parts):
            full_filename = os.path.join(base_dir, contract_name+".sol")
            print("Writing file:", bcolors.OKBLUE, full_filename, bcolors.ENDC)
            with open(full_filename, "w") as f:
                f.write(codes)
            return

        last_file = ""
        for (filename, code) in each_files:
            full_filename = os.path.join(base_dir, os.path.basename(filename))
            print("Writing file:", bcolors.OKBLUE, full_filename, bcolors.ENDC)
            with open(full_filename, "w") as f:
                f.write((f"import \"./{last_file}\";\r\n" if last_file else "") + code.strip("\r\n"))

            last_file = os.path.basename(filename)

def write_txtfile(filename, content, dir):
    print("Writing file:", bcolors.OKBLUE, os.path.join(dir,filename), bcolors.ENDC)
    with open(os.path.join(dir, filename), "w") as f:
        f.write(content)

def work():

    res = get_sourcecode()

    contract_name = res['result'][0]['ContractName']
    codes = res['result'][0]['SourceCode']
    base_dir = os.path.join(os.getcwd(), "contracts", contract_name)

    # Source code
    create_directory(base_dir + "/sourcecode")  # create directory: ./contracts/{contract name}/sourcecode
    write_srcfiles(codes, contract_name, base_dir + "/sourcecode")

    # Bytecode
    bytecode = get_bytecode()
    create_directory(base_dir + "/bytecode")  # create directory: ./contracts/{contract name}/bytecode
    write_txtfile('bytecode.txt', bytecode, base_dir + "/bytecode")

    # Opcode
    opcode = get_opcode()
    create_directory(base_dir + "/opcode")  # create directory: ./contracts/{contract name}/opcode
    write_txtfile('opcode.txt', opcode, base_dir + "/opcode")


        
def main():
    pre_check()
    work()


if __name__ == "__main__":
    main()
