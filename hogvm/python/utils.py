import re
from typing import Any


COST_PER_UNIT = 8


class HogVMException(Exception):
    pass


def like(string, pattern, flags=0):
    pattern = re.escape(pattern).replace("%", ".*")
    re_pattern = re.compile(pattern, flags)
    return re_pattern.search(string) is not None


def get_nested_value(obj, chain, nullish=False) -> Any:
    if obj is None:
        return None
    for key in chain:
        if nullish and obj is None:
            return None
        if isinstance(key, int):
            if nullish and len(obj) <= key:
                return None
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


def calculate_cost(object) -> int:
    if isinstance(object, dict):
        return COST_PER_UNIT + sum([calculate_cost(key) + calculate_cost(value) for key, value in object.items()])
    elif isinstance(object, list) or isinstance(object, tuple):
        return COST_PER_UNIT + sum([calculate_cost(val) for val in object])
    elif object is None:
        return COST_PER_UNIT
    elif isinstance(object, str):
        return COST_PER_UNIT + len(object)
    elif isinstance(object, int):
        return COST_PER_UNIT
    else:
        return COST_PER_UNIT
