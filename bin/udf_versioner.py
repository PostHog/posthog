import argparse
import os
import shutil
import glob
import xml.etree.ElementTree as ET

parser = argparse.ArgumentParser(description="Create a new version for UDF deployment.")
parser.add_argument("-f", "--force", action="store_true", help="override existing directories")
args = parser.parse_args()

# Increment this and run this file every time you make breaking changes to UDFs
# After running this, you have to copy the `user_defined_function.xml` file to the charts repo and deploy it
# After it goes out, it is safe to land the posthog repo code
# If deploys aren't seamless, look into movie the copy to clickhouse earlier in the deploy process
UDF_VERSION = 1

XML_CONFIG = "user_defined_function.xml"

make_version_dir = lambda version: f"v{version}"
NEW_VERSION_DIR = make_version_dir(UDF_VERSION)
LAST_VERSION_DIR = make_version_dir(UDF_VERSION - 1)

os.chdir("../posthog/user_scripts")
if args.force:
    shutil.rmtree(NEW_VERSION_DIR)
try:
    os.mkdir(NEW_VERSION_DIR)
except FileExistsError:
    if not args.force:
        raise FileExistsError(
            f"A directory already exists for this version at posthog/user_scripts/{NEW_VERSION_DIR}. Did you forget to increment the version? If not, delete the folder and run this again, or run this script with a -f"
        )
for file in glob.glob("*.py"):
    shutil.copy(file, NEW_VERSION_DIR)

base_xml = ET.parse(XML_CONFIG)

if os.path.exists(LAST_VERSION_DIR):
    last_version_xml = ET.parse(os.path.join(LAST_VERSION_DIR, XML_CONFIG))
else:
    last_version_xml = ET.parse(XML_CONFIG)

last_version_root = last_version_xml.getroot()
# We want to update the name and the command to include the version, and add it to last version
for function in list(base_xml.getroot()):
    name = function.find("name")
    name.text = f"{name.text}_{NEW_VERSION_DIR}"
    command = function.find("command")
    command.text = f"{NEW_VERSION_DIR}/{command.text}"
    last_version_root.append(function)

last_version_xml.write(os.path.join(NEW_VERSION_DIR, XML_CONFIG))
