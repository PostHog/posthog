from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from posthog.schema import QueryTiming

from posthog.query_cache.results import fetch_entry
from posthog.query_cache.serialization import (
    QUERY_CACHE_SPLIT_MAGIC,  # noqa: F401, re-exported for existing importers during the transition
    CachedEntry as SplitCachedResponse,
    encode_split_cached_response,  # noqa: F401, re-exported for existing importers during the transition
    results_have_custom_names,  # noqa: F401, re-exported for existing importers during the transition
)


def fetch_split_cached_response_by_key(cache_key: str, team_id: int) -> Optional[SplitCachedResponse]:
    return fetch_entry(cache_key, team_id)


def fetch_cached_response_by_key(cache_key: str, team_id: int) -> Optional[dict]:
    entry = fetch_entry(cache_key, team_id)
    return entry.as_full_response() if entry else None


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
