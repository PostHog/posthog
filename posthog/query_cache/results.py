from typing import Optional

from django.core.cache import caches

import structlog

from posthog.caching.redis_cluster_connection_factory import QUERY_CACHE_ALIAS
from posthog.query_cache.serialization import CachedEntry, split_cached_response_bytes

logger = structlog.get_logger(__name__)


def fetch_entry(cache_key: str, team_id: int) -> Optional[CachedEntry]:
    query_cache = caches[QUERY_CACHE_ALIAS]
    try:
        cached_response_bytes = query_cache.get(cache_key)
    except Exception:
        logger.warning("query_cache_read_error", cache_key=cache_key, team_id=team_id, exc_info=True)
        try:
            query_cache.delete(cache_key)
        except Exception:
            pass
        return None

    if not cached_response_bytes:
        return None

    try:
        return split_cached_response_bytes(cached_response_bytes, cache_key=cache_key, team_id=team_id)
    except Exception:
        logger.exception("query_cache_deserialize_error", cache_key=cache_key, team_id=team_id, exc_info=True)
        return None
