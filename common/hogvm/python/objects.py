from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class CallFrame:
    ip: int
    chunk: str
    stack_start: int
    arg_len: int
    closure: dict


@dataclass
class ThrowFrame:
    call_stack_len: int
    stack_len: int
    catch_ip: int


def is_hog_date(obj: Any) -> bool:
    return isinstance(obj, dict) and "__hogDate__" in obj and "year" in obj and "month" in obj and "day" in obj


def is_hog_datetime(obj: Any) -> bool:
    return isinstance(obj, dict) and "__hogDateTime__" in obj and "dt" in obj and "zone" in obj


def is_hog_error(obj: Any) -> bool:
    return isinstance(obj, dict) and "__hogError__" in obj and "type" in obj and "message" in obj


def new_hog_error(type: str, message: Any, payload: Any = None) -> dict:
    return {
        "__hogError__": True,
        "type": type or "Error",
        "message": message or "An error occurred",
        "payload": payload,
    }


def is_hog_callable(obj: Any) -> bool:
    return (
        isinstance(obj, dict)
        and "__hogCallable__" in obj
        and "argCount" in obj
        and "ip" in obj
        # and "chunk" in obj # TODO: enable after this has been live for some hours
        and "upvalueCount" in obj
    )


def is_hog_closure(obj: Any) -> bool:
    return isinstance(obj, dict) and "__hogClosure__" in obj and "callable" in obj and "upvalues" in obj


def new_hog_closure(callable: dict, upvalues: Optional[list] = None) -> dict:
    return {
        "__hogClosure__": True,
        "callable": callable,
        "upvalues": upvalues or [],
    }


def new_hog_callable(type: str, arg_count: int, upvalue_count: int, ip: int, name: str, chunk: str) -> dict:
    return {
        "__hogCallable__": type,
        "name": name,
        "chunk": chunk,
        "argCount": arg_count,
        "upvalueCount": upvalue_count,
        "ip": ip,
    }


def is_hog_upvalue(obj: Any) -> bool:
    return (
        isinstance(obj, dict)
        and "__hogUpValue__" in obj
        and "location" in obj
        and "closed" in obj
        and "value" in obj
        and "id" in obj
    )


def is_hog_interval(obj: Any) -> bool:
    return isinstance(obj, dict) and obj.get("__hogInterval__") is True


def to_hog_interval(value: int, unit: str):
    return {
        "__hogInterval__": True,
        "value": value,
        "unit": unit,
    }
