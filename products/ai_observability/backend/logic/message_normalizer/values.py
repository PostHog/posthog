import re
import json
from collections.abc import Mapping, Sequence
from typing import Final, TypeGuard


class Missing:
    __slots__ = ()

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


# Recipes rely on JavaScript telling a missing field (`undefined`) apart from `null`: `exists` sees a null
# field as present, and an emit whose content is missing may drop the message where a null content may not.
MISSING: Final = Missing()

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type Value = None | bool | int | float | str | Missing | Sequence[Value] | Mapping[str, Value]
type CompatMessage = dict[str, JsonValue]


def is_number(value: Value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def is_mapping(value: Value) -> TypeGuard[Mapping[str, Value]]:
    return isinstance(value, Mapping)


def is_list(value: Value) -> TypeGuard[Sequence[Value]]:
    return isinstance(value, Sequence) and not isinstance(value, str)


def is_object_like(value: Value) -> bool:
    return is_mapping(value) or is_list(value)


def strict_equals(left: Value, right: Value) -> bool:
    if isinstance(left, Missing) or isinstance(right, Missing):
        return left is right
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if is_number(left) and is_number(right):
        return left == right
    if is_object_like(left) or is_object_like(right):
        return False
    return type(left) is type(right) and left == right


def is_truthy(value: Value) -> bool:
    if value is None or isinstance(value, Missing):
        return False
    if is_object_like(value):
        return True
    if isinstance(value, float) and value != value:
        return False
    return bool(value)


def has_field(value: Value, field: str) -> bool:
    return is_mapping(value) and field in value


_LIST_INDEX: Final = re.compile(r"0|[1-9][0-9]*")


def read_field(value: Value, field: str) -> Value:
    if is_mapping(value) and field in value:
        return value[field]
    if is_list(value) and _LIST_INDEX.fullmatch(field) and int(field) < len(value):
        return value[int(field)]
    return MISSING


def read_path(value: Value, segments: Sequence[str]) -> Value:
    cursor = value
    for segment in segments:
        cursor = read_field(cursor, segment)
        if isinstance(cursor, Missing):
            return cursor
    return cursor


def to_json_value(value: Value) -> JsonValue:
    if isinstance(value, Missing):
        return None
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, Mapping):
        return {key: to_json_value(item) for key, item in value.items() if not isinstance(item, Missing)}
    return [to_json_value(item) for item in value]


def to_json_text(value: Value) -> str:
    return json.dumps(to_json_value(value), ensure_ascii=False, separators=(",", ":"))


def to_text(value: Value) -> str:
    if isinstance(value, str):
        return value
    if value is None or isinstance(value, Missing):
        return ""
    return to_json_text(value)
