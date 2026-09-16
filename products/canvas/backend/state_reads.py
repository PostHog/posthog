import json
import hashlib
from typing import Any

from django.db.models import QuerySet

from products.canvas.backend.models import CanvasState


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
    ) -> dict[str, Any]:
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
        return {
            "entries": rows[:limit] if limit is not None else rows,
            "next_offset": offset + limit if has_more and limit is not None else None,
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
