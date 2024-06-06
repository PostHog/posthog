import sys
import json
from .execute import execute_bytecode

# get modifiers
modifiers = [arg for arg in sys.argv if arg.startswith("-")]

# get filename from first cli arg
args = [arg for arg in sys.argv if arg != "" and not arg.startswith("-")]
filename = args[1]

debug = "--debug" in modifiers

# raise if filename does not end with ".hoge"
if not filename.endswith(".hoge"):
    raise ValueError("filename must end with '.hoge'. Got: " + filename)

# read file
with open(filename) as file:
    code = file.read()
    code = json.loads(code)

# execute code
response = execute_bytecode(code, globals=None, timeout=5, team=None, debug=debug)
for line in response.stdout:
    print(line)  # noqa: T201
