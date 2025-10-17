import re
from typing import Any

COST_PER_UNIT = 8


class HogVMException(Exception):
    pass


class UncaughtHogVMException(HogVMException):
    type: str
    message: str
    payload: Any

    def __init__(self, type, message, payload):
        super().__init__(message)
        self.type = type
        self.message = message
        self.payload = payload

    def __str__(self):
        msg = self.message.replace("'", "\\'")
        return f"{self.type}('{msg}')"


class HogVMRuntimeExceededException(HogVMException):
    """Exception thrown when HogVM code exceeds its runtime limit"""

    def __init__(self, timeout_seconds: float, ops_performed: int):
        self.timeout_seconds = timeout_seconds
        self.ops_performed = ops_performed
        super().__init__(f"Runtime exceeded {timeout_seconds} seconds after {ops_performed} operations")


class HogVMMemoryExceededException(HogVMException):
    """Exception thrown when HogVM code exceeds its memory limit"""

    def __init__(self, memory_limit: int, attempted_memory: int):
        self.memory_limit = memory_limit
        self.attempted_memory = attempted_memory
        super().__init__(f"Memory limit of {memory_limit} bytes exceeded. Attempted to use {attempted_memory} bytes")


def like(string, pattern, flags=0):
    pattern = re.escape(pattern).replace("%", ".*").replace("_", ".")
    re_pattern = re.compile(pattern, flags)
    return re_pattern.search(string) is not None


def get_nested_value(obj, chain, nullish=False) -> Any:
    if obj is None:
        return None
    for key in chain:
        if nullish and obj is None:
            return None
        if isinstance(key, int):
            if key == 0:
                raise HogVMException(f"Hog arrays start from index 1")
            elif key > 0:
                if key > len(obj):
                    return None
                obj = obj[key - 1]
            elif key < 0:
                if -key > len(obj):
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
        if chain[-1] <= 0:
            raise HogVMException(f"Hog arrays start from index 1")
        obj[chain[-1] - 1] = value
    else:
        raise HogVMException(f'Can not set property "{chain[-1]}" on object of type "{type(obj).__name__}"')

    return obj


def calculate_cost(object, marked: set | None = None) -> int:
    if marked is None:
        marked = set()
    if isinstance(object, dict) or isinstance(object, list) or isinstance(object, tuple):
        if id(object) in marked:
            return COST_PER_UNIT
        marked.add(id(object))
        try:
            if isinstance(object, dict):
                return COST_PER_UNIT + sum(
                    [calculate_cost(key, marked) + calculate_cost(value, marked) for key, value in object.items()]
                )
            elif isinstance(object, list) or isinstance(object, tuple):
                return COST_PER_UNIT + sum([calculate_cost(val, marked) for val in object])
        finally:
            marked.remove(id(object))
    elif isinstance(object, str):
        return COST_PER_UNIT + len(object)
    return COST_PER_UNIT


def unify_comparison_types(left, right):
    if isinstance(left, int | float) and isinstance(right, str):
        return left, float(right)
    if isinstance(left, str) and isinstance(right, int | float):
        return float(left), right
    if isinstance(left, bool) and isinstance(right, str):
        return left, bool(right)
    if isinstance(left, str) and isinstance(right, bool):
        return bool(left), right
    if isinstance(left, int | float) and isinstance(right, bool):
        return left, int(right)
    if isinstance(left, bool) and isinstance(right, int | float):
        return int(left), right
    return left, right
