from typing import Optional

import structlog

from posthog.dataclasses import frozen
from posthog.query_cache.serialization import CachedEntry, split_cached_response_bytes
from posthog.query_cache.storage import (
    decode_pointer,
    decode_stored_value,
    delete_entry,
    is_s3_pointer,
    load_entry_value,
)

logger = structlog.get_logger(__name__)


@frozen
class EntryFreshness:
    """What a freshness probe learns from Redis alone: the entry exists, and when it was
    last refreshed (None when the stored response carries no last_refresh)."""

    last_refresh: Optional[str]


def fetch_entry(cache_key: str, team_id: int) -> Optional[CachedEntry]:
    try:
        stored_value = load_entry_value(cache_key)
    except Exception:
        logger.warning("query_cache_read_error", cache_key=cache_key, team_id=team_id, exc_info=True)
        try:
            delete_entry(cache_key)
        except Exception:
            pass
        return None

    if not stored_value:
        return None

    payload = decode_stored_value(stored_value, team_id=team_id, cache_key=cache_key)
    if payload is None:
        return None

    try:
        return split_cached_response_bytes(payload, cache_key=cache_key, team_id=team_id)
    except Exception:
        logger.exception("query_cache_deserialize_error", cache_key=cache_key, team_id=team_id, exc_info=True)
        return None


def fetch_entry_freshness(cache_key: str, team_id: int) -> Optional[EntryFreshness]:
    """Existence and last_refresh of an entry without resolving S3 pointers. Never raises.

    Pointer records carry last_refresh, so probing an S3-backed entry costs one Redis read;
    resolving the blob here would put an S3 round trip into every warming candidate check.
    The trade: a pointer whose blob has died still reads as a live entry until the recompute
    that follows a real read's miss overwrites it.
    """
    try:
        stored_value = load_entry_value(cache_key)
        if not stored_value:
            return None
        if is_s3_pointer(stored_value):
            pointer = decode_pointer(stored_value)
            if pointer is None:
                return None
            return EntryFreshness(last_refresh=pointer.last_refresh)
        payload = decode_stored_value(stored_value, team_id=team_id, cache_key=cache_key)
        if payload is None:
            return None
        entry = split_cached_response_bytes(payload, cache_key=cache_key, team_id=team_id)
        last_refresh = entry.header.get("last_refresh")
        return EntryFreshness(last_refresh=last_refresh if isinstance(last_refresh, str) else None)
    except Exception:
        logger.warning("query_cache_freshness_probe_failed", cache_key=cache_key, team_id=team_id, exc_info=True)
        return None
