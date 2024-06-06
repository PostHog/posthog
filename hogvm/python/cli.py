import sys
import json
from .execute import execute_bytecode

# get filename from first cli arg
args = [arg for arg in sys.argv if arg != ""]
filename = args[1]

# raise if filename does not end with ".hoge"
if not filename.endswith(".hoge"):
    raise ValueError("filename must end with '.hoge'. Got: " + filename)

# read file
with open(filename) as file:
    code = file.read()
    code = json.loads(code)

# execute code
execute_bytecode(code, globals=None, functions=None, timeout=10, team=None)
