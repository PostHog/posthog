from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from django.core.cache import caches

import structlog
from prometheus_client import Counter

from posthog.schema import QueryTiming

from posthog.cache_utils import OrjsonJsonSerializer
from posthog.caching.redis_cluster_connection_factory import QUERY_CACHE_ALIAS
from posthog.query_cache.serialization import (
    QUERY_CACHE_SPLIT_MAGIC,  # noqa: F401, re-exported for existing importers during the transition
    CachedEntry as SplitCachedResponse,
    encode_split_cached_response,  # noqa: F401, re-exported for existing importers during the transition
    results_have_custom_names,  # noqa: F401, re-exported for existing importers during the transition
    split_cached_response_bytes,
)

logger = structlog.get_logger(__name__)

insight_cache_read_counter = Counter(
    "posthog_cloud_insight_cache_read",
    "A read from the redis insight cache",
    labelnames=["result"],
)


def fetch_split_cached_response_by_key(cache_key: str, team_id: int) -> Optional[SplitCachedResponse]:
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
        return split_cached_response_bytes(cached_response_bytes)
    except Exception:
        logger.exception(
            "query_cache_deserialize_error",
            cache_key=cache_key,
            team_id=team_id,
            exc_info=True,
        )
        return None


def fetch_cached_response_by_key(cache_key: str, team_id: int) -> Optional[dict]:
    split = fetch_split_cached_response_by_key(cache_key, team_id)
    if split is None:
        return None
    if split.results_bytes is None:
        return split.header
    try:
        split.header["results"] = OrjsonJsonSerializer({}).loads(split.results_bytes)
    except Exception:
        logger.exception("query_cache_deserialize_error", cache_key=cache_key, team_id=team_id, exc_info=True)
        return None
    return split.header


@dataclass(frozen=True)
class InsightResult:
    result: Optional[Any]
    last_refresh: Optional[datetime]
    cache_key: Optional[str]
    is_cached: bool
    timezone: Optional[str]
    has_more: Optional[bool] = None
    next_allowed_client_refresh: Optional[datetime] = None
    cache_target_age: Optional[datetime] = None
    timings: Optional[list[QueryTiming]] = None
    columns: Optional[list] = None
    query_status: Optional[Any] = None
    hogql: Optional[str] = None
    types: Optional[list] = None
    # A ResolvedDateRangeResponse-shaped dict — the field carries model_dump output
    resolved_date_range: Optional[dict] = None


@dataclass(frozen=True)
class NothingInCacheResult(InsightResult):
    result: Optional[Any] = None
    last_refresh: Optional[datetime] = None
    cache_key: Optional[str] = None
    is_cached: bool = False
    timezone: Optional[str] = None
    next_allowed_client_refresh: Optional[datetime] = None
    columns: Optional[list] = None
