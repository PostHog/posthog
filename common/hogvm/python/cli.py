import sys
import json
from datetime import timedelta

from .execute import execute_bytecode

modifiers = [arg for arg in sys.argv if arg.startswith("-")]
args = [arg for arg in sys.argv if arg != "" and not arg.startswith("-")]
if len(args) != 2:
    raise ValueError("Must specify exactly one filename")

filename = args[1]

debug = "--debug" in modifiers

if not filename.endswith(".hoge"):
    raise ValueError("filename must end with '.hoge'. Got: " + filename)

with open(filename) as file:
    code = file.read()
    code = json.loads(code)

response = execute_bytecode(code, globals=None, timeout=timedelta(seconds=5), team=None, debug=debug)
for line in response.stdout:
    print(line)  # noqa: T201
