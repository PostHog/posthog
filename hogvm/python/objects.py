from typing import Any


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
