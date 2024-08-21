from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class CallFrame:
    ip: int
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
    return isinstance(obj, dict) and "__hogCallable__" in obj and "args" in obj and "body" in obj


def is_hog_closure(obj: Any) -> bool:
    return isinstance(obj, dict) and "__hogClosure__" in obj and "callable" in obj and "captured" in obj


def new_hog_closure(callable: dict, captured: Optional[dict] = None) -> dict:
    return {
        "__hogClosure__": True,
        "callable": callable,
        "captured": captured or [],
    }
