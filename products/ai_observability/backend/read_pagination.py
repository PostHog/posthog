import json
import base64
import binascii
from collections.abc import Callable

from posthog.dataclasses import frozen


def encode_cursor(values: list[str]) -> str:
    return base64.urlsafe_b64encode(json.dumps(values, separators=(",", ":")).encode()).decode().rstrip("=")


def decode_cursor(cursor: str, expected_parts: int) -> list[str]:
    try:
        if len(cursor) > 2048:
            raise ValueError
        decoded = json.loads(base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True))
        if (
            not isinstance(decoded, list)
            or len(decoded) != expected_parts
            or not all(isinstance(value, str) for value in decoded)
        ):
            raise ValueError
        return decoded
    except (ValueError, UnicodeDecodeError, binascii.Error) as error:
        raise ValueError("Provide a valid continuation cursor.") from error


@frozen
class CursorPage[T]:
    count: int
    next_cursor: str | None
    results: list[T]


def cursor_page[T](rows: list[T], *, count: int, limit: int, cursor_for: Callable[[T], str]) -> CursorPage[T]:
    results = rows[:limit]
    next_cursor = cursor_for(results[-1]) if len(rows) > limit else None
    return CursorPage(count=count, next_cursor=next_cursor, results=results)
