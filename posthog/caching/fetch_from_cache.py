from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import structlog
from prometheus_client import Counter

from posthog.schema import QueryTiming, ResolvedDateRangeResponse

from posthog.cache_utils import OrjsonJsonSerializer
from posthog.utils import get_safe_cache

logger = structlog.get_logger(__name__)

insight_cache_read_counter = Counter(
    "posthog_cloud_insight_cache_read",
    "A read from the redis insight cache",
    labelnames=["result"],
)


def fetch_cached_response_by_key(cache_key: str) -> Optional[dict]:
    cached_response_bytes: Optional[bytes] = get_safe_cache(cache_key)

    if not cached_response_bytes:
        logger.warning(
            "export_cache_miss",
            cache_key=cache_key,
            message="Expected cache key not found - cache may have expired or key mismatch",
        )
        return None

    try:
        return OrjsonJsonSerializer({}).loads(cached_response_bytes)
    except Exception:
        logger.exception(
            "export_cache_deserialize_error",
            cache_key=cache_key,
        )
        return None


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
    resolved_date_range: Optional[ResolvedDateRangeResponse] = None


@dataclass(frozen=True)
class NothingInCacheResult(InsightResult):
    result: Optional[Any] = None
    last_refresh: Optional[datetime] = None
    cache_key: Optional[str] = None
    is_cached: bool = False
    timezone: Optional[str] = None
    next_allowed_client_refresh: Optional[datetime] = None
    columns: Optional[list] = None
