import time
from typing import Any
import re
import requests

from hogvm.python.utils import HogVMException


def _to_concat_arg(arg) -> str:
    if arg is None:
        return ""
    if arg is True:
        return "true"
    if arg is False:
        return "false"
    return str(arg)


def execute_stl_function(name: str, args: list[Any], timeout=5):
    match name:
        case "concat":
            return "".join([_to_concat_arg(arg) for arg in args])
        case "match":
            return bool(re.search(re.compile(args[1]), args[0]))
        case "toString" | "toUUID":
            if args[0] is True:
                return "true"
            elif args[0] is False:
                return "false"
            elif args[0] is None:
                return "null"
            else:
                return str(args[0])
        case "toInt" | "toFloat":
            try:
                return int(args[0]) if name == "toInt" else float(args[0])
            except ValueError:
                return None
        case "ifNull":
            if args[0] is not None:
                return args[0]
            else:
                return args[1]
        case "length":
            return len(args[0])
        case "empty":
            return not bool(args[0])
        case "notEmpty":
            return bool(args[0])
        case "lower":
            return args[0].lower()
        case "upper":
            return args[0].upper()
        case "reverse":
            return args[0][::-1]
        case "httpGet":
            response = requests.get(args[0], timeout=timeout)
            return response.text
        case "sleep":
            time.sleep(args[0])
            return None
        case "print":
            print(*args)  # noqa: T201
            return None
        case _:
            raise HogVMException(f"Unsupported function call: {name}")
