import re
import json
import math
from collections.abc import Mapping, Sequence
from typing import Final, NoReturn, TypeGuard

from .run_limits import MAX_PARSE_CHARS, charge_output, check_time_limit


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
    if is_mapping(value):
        return field in value
    return is_list(value) and (field == _LIST_LENGTH or _list_index(value, field) is not None)


def read_field(value: Value, field: str) -> Value:
    if is_mapping(value) and field in value:
        return value[field]
    if is_list(value):
        if field == _LIST_LENGTH:
            return len(value)
        if (index := _list_index(value, field)) is not None:
            return value[index]
    return MISSING


# The frontend engine reads a field with JavaScript's `in`, which finds an array's `length`, so recipes can count items.
_LIST_LENGTH: Final = "length"


_LIST_INDEX: Final = re.compile(r"0|[1-9][0-9]*")


def _list_index(value: Sequence[Value], field: str) -> int | None:
    # An index with more digits than the length cannot be in range, and checking that first keeps `int()` from
    # raising on text past Python's integer string conversion limit.
    if not _LIST_INDEX.fullmatch(field) or len(field) > len(str(len(value))):
        return None
    index = int(field)
    return index if index < len(value) else None


def read_path(value: Value, segments: Sequence[str]) -> Value:
    cursor = value
    for segment in segments:
        cursor = read_field(cursor, segment)
        if isinstance(cursor, Missing):
            return cursor
    return cursor


def to_json_value(value: Value) -> JsonValue:
    return _materialize(value, as_json_text=False)


def _materialize(value: Value, as_json_text: bool) -> JsonValue:
    if isinstance(value, str):
        charge_output(nodes=1, chars=_json_string_length(value) if as_json_text else len(value))
        return value
    if isinstance(value, Mapping):
        # As text, every entry adds a colon and a comma to its quoted key, and the mapping adds its braces.
        key_chars = 2 + sum(_json_string_length(key) + 2 for key in value) if as_json_text else sum(map(len, value))
        charge_output(nodes=1, chars=key_chars)
        return {key: _materialize(item, as_json_text) for key, item in value.items() if not isinstance(item, Missing)}
    if isinstance(value, Sequence):
        charge_output(nodes=1, chars=len(value) + 2 if as_json_text else 0)
        return [_materialize(item, as_json_text) for item in value]
    # JSON has no NaN or Infinity, and JavaScript's JSON.stringify writes them as null.
    scalar = None if isinstance(value, Missing) or (isinstance(value, float) and not math.isfinite(value)) else value
    charge_output(nodes=1, chars=_json_scalar_length(scalar) if as_json_text else 0)
    return scalar


# json.dumps writes these as a two-character escape such as `\n`, and every other control character as `\u00XX`.
_SHORT_ESCAPES: Final = ('"', "\\", "\n", "\r", "\t", "\b", "\f")
_UNICODE_ESCAPES: Final = tuple(chr(code) for code in range(0x20) if chr(code) not in _SHORT_ESCAPES)
_ANY_ESCAPE: Final = re.compile(r'[\x00-\x1f"\\]')
_ANY_UNICODE_ESCAPE: Final = re.compile(f"[{re.escape(''.join(_UNICODE_ESCAPES))}]")
_DROP_UNICODE_ESCAPES: Final = str.maketrans(dict.fromkeys(_UNICODE_ESCAPES))
_SCAN_CHUNK_CHARS: Final = 1 << 20


def _json_string_length(text: str) -> int:
    # Escapes can make the text six times longer than the string, so the walk charges the escaped length.
    if not _ANY_ESCAPE.search(text):
        return len(text) + 2
    escapes = sum(map(text.count, _SHORT_ESCAPES))
    if _ANY_UNICODE_ESCAPE.search(text):
        escapes += 5 * _count_unicode_escapes(text)
    return len(text) + 2 + escapes


def _count_unicode_escapes(text: str) -> int:
    # Dropping the characters with `str.translate` counts all of them in one C pass, where a count per character would
    # take 25 passes. Going chunk by chunk holds at most one chunk's copy at a time.
    chunks = (text[start : start + _SCAN_CHUNK_CHARS] for start in range(0, len(text), _SCAN_CHUNK_CHARS))
    return sum(len(chunk) - len(chunk.translate(_DROP_UNICODE_ESCAPES)) for chunk in chunks)


def _json_scalar_length(value: JsonValue) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        # A decimal digit holds more than three bits, so this bounds the digits and the sign.
        return value.bit_length() // 3 + 2
    # Long enough for `false`, `null` and the longest float text, such as `-2.2250738585072014e-308`.
    return 24


def to_json_text(value: Value) -> str:
    # The walk charges the text json.dumps will write, quotes, escapes and punctuation included, before it is written.
    return _dump(_materialize(value, as_json_text=True))


def parse_json_text(text: str) -> JsonValue:
    if len(text) > MAX_PARSE_CHARS:
        raise ValueError(f"JSON text longer than {MAX_PARSE_CHARS} characters is not parsed")
    # A failed parse charges nothing, so no budget check would see the clock. A recipe can point many tool calls at the
    # same invalid text, and this check stops the run within one parse of its time limit.
    check_time_limit()
    try:
        # JavaScript's JSON.parse rejects NaN and Infinity, so a recipe keeps such text as a string on both sides.
        return json.loads(text, parse_constant=_reject_constant, parse_float=_finite_float)
    except RecursionError as error:
        raise ValueError("JSON text nests too deeply to parse") from error


def charge_kept_parse(text: str, parsed: JsonValue) -> None:
    # A dropped parse is never charged, because its text was charged when it was built or came from the event. A kept
    # parse can be held once per item of a list, so it pays for its text and for every value it holds. The walk charges
    # each container before it visits the children, so it stops at the cap.
    charge_output(nodes=1, chars=len(text))
    pending: list[JsonValue] = [parsed]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            charge_output(nodes=len(value))
            pending.extend(value.values())
        elif isinstance(value, list):
            charge_output(nodes=len(value))
            pending.extend(value)


def _reject_constant(constant: str) -> NoReturn:
    raise ValueError(f"{constant} is not valid JSON")


def _finite_float(literal: str) -> float:
    # An overflowing literal such as `1e999` parses to infinity, which serializes as null, so the text is kept instead.
    value = float(literal)
    if not math.isfinite(value):
        raise ValueError(f"{literal} overflows a double")
    return value


def key_text(key: object) -> str:
    # JavaScript turns every object key into a string, so a YAML `1:` or `true:` key names the field "1" or "true".
    if isinstance(key, str):
        return key
    if key is None or isinstance(key, bool | int | float):
        return to_json_text(key)
    return str(key)


def to_text(value: Value) -> str:
    if value is None or isinstance(value, Missing):
        return ""
    if isinstance(value, str):
        # Strings are charged too, so interpolation and join pay for every character they concatenate.
        charge_output(nodes=1, chars=len(value))
        return value
    return to_json_text(value)


def _dump(value: JsonValue) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
