from typing import Optional

import structlog

from posthog.query_cache.serialization import CachedEntry, split_cached_response_bytes
from posthog.query_cache.storage import decode_stored_value, delete_entry, load_entry_value

logger = structlog.get_logger(__name__)


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
