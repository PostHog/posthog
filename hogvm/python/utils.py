import re
from typing import Any


class HogVMException(Exception):
    pass


def like(string, pattern, flags=0):
    pattern = re.escape(pattern).replace("%", ".*")
    re_pattern = re.compile(pattern, flags)
    return re_pattern.search(string) is not None


def get_nested_value(obj, chain) -> Any:
    if obj is None:
        return None
    for key in chain:
        if isinstance(key, int):
            obj = obj[key]
        else:
            obj = obj.get(key, None)
    return obj


def set_nested_value(obj, chain, value) -> Any:
    if obj is None:
        return None
    for key in chain[:-1]:
        if isinstance(key, int):
            obj = obj[key]
        else:
            obj = obj.get(key, None)

    if isinstance(obj, dict):
        obj[chain[-1]] = value
    elif isinstance(obj, list):
        if not isinstance(chain[-1], int):
            raise HogVMException(f"Invalid index: {chain[-1]}")
        obj[chain[-1]] = value
    else:
        raise HogVMException(f'Can not set property "{chain[-1]}" on object of type "{type(obj).__name__}"')

    return obj
