"""Encode JSON with orjson when a payload can hold integers wider than 64 bits.

ClickHouse UInt128, Int128, UInt256 and Int256 values, such as the sessions table's
``session_id_v7``, arrive as Python ints. orjson refuses ints outside the signed and unsigned
64-bit range, so a query that selects one fails when its response is cached or rendered.
Those ints are sent as strings, which is what ClickHouse's own JSON output does, because a
JSON number that large loses precision in every JavaScript client.
"""

from collections.abc import Callable
from typing import Any

import orjson

WIDE_INT_ERROR = "Integer exceeds 64-bit range"


def stringify_wide_ints(value: Any) -> Any:
    if isinstance(value, int) and not isinstance(value, bool) and not (-(2**63) <= value < 2**64):
        return str(value)
    if isinstance(value, dict):
        return {key: stringify_wide_ints(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [stringify_wide_ints(item) for item in value]
    return value


def dumps(value: Any, *, default: Callable[[Any], Any] | None = None, option: int | None = None) -> bytes:
    try:
        return orjson.dumps(value, default=default, option=option)
    except orjson.JSONEncodeError as error:
        if str(error) != WIDE_INT_ERROR:
            raise
    return orjson.dumps(stringify_wide_ints(value), default=default, option=option)
