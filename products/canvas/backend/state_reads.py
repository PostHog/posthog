import json
import base64
import hashlib
from typing import Any

from django.db.models import Q, QuerySet

from products.canvas.backend.models import CanvasState


def encode_state_cursor(scope: str, key: str) -> str:
    # UTF-8 without ASCII escapes, so a cursor for any valid key stays within the query parameter limit.
    payload = json.dumps([scope, key], separators=(",", ":"), ensure_ascii=False)
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_state_cursor(cursor: str) -> tuple[str, str]:
    """The (scope, key) of the last entry a page returned. Raises ValueError for a malformed cursor."""
    try:
        decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (ValueError, TypeError) as error:
        raise ValueError("Invalid state cursor.") from error
    if not isinstance(decoded, list) or len(decoded) != 2 or not all(isinstance(part, str) for part in decoded):
        raise ValueError("Invalid state cursor.")
    return decoded[0], decoded[1]


class CanvasStateReader:
    @staticmethod
    def entries(
        queryset: QuerySet[CanvasState],
        *,
        scope: str | None = None,
        key: str | None = None,
        key_prefix: str | None = None,
        keys_only: bool = False,
        offset: int = 0,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """One page of entries, ordered by scope and key.

        A cursor resumes after the last entry of the previous page, so an entry
        that exists for the whole read comes back exactly once, whatever other
        keys change between pages. A key written between pages can be missing
        when it sorts before the cursor. An offset counts rows, so a delete
        between pages can make it skip an entry that existed all along. A
        cursor takes precedence over `offset`.
        """
        if cursor is not None:
            after_scope, after_key = decode_state_cursor(cursor)
            queryset = queryset.filter(Q(scope__gt=after_scope) | Q(scope=after_scope, key__gt=after_key))
            offset = 0
        if scope:
            queryset = queryset.filter(scope=scope)
        if key is not None:
            queryset = queryset.filter(key=key)
        if key_prefix:
            queryset = queryset.filter(key__startswith=key_prefix)
        # A scope holds up to 256 keys of 64 KB, so a whole-scope read can exceed what the caller can hold.
        fields = ["scope", "key", "updated_at"]
        if not keys_only:
            fields.append("value")
        selected = queryset.order_by("scope", "key").values(*fields)
        rows = list(selected[offset : offset + limit + 1] if limit is not None else selected[offset:])
        has_more = limit is not None and len(rows) > limit
        page = rows[:limit] if limit is not None else rows
        return {
            "entries": page,
            "next_offset": offset + limit if has_more and limit is not None and cursor is None else None,
            "next_cursor": encode_state_cursor(page[-1]["scope"], page[-1]["key"]) if has_more else None,
            "complete": not has_more,
        }

    @staticmethod
    def value(entry: CanvasState, *, offset: int, limit: int) -> dict[str, Any]:
        encoded = json.dumps(entry.value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        next_offset = offset + limit if offset + limit < len(encoded) else None
        return {
            "scope": entry.scope,
            "key": entry.key,
            "value_json": encoded[offset : offset + limit],
            "revision": hashlib.sha256(encoded.encode()).hexdigest(),
            "offset": offset,
            "total_length": len(encoded),
            "next_offset": next_offset,
            "complete": next_offset is None,
        }
