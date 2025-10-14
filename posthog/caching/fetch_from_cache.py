from dataclasses import dataclass
from datetime import datetime
from typing import Any

from prometheus_client import Counter

from posthog.schema import QueryTiming

insight_cache_read_counter = Counter(
    "posthog_cloud_insight_cache_read",
    "A read from the redis insight cache",
    labelnames=["result"],
)


@dataclass(frozen=True)
class InsightResult:
    result: Any | None
    last_refresh: datetime | None
    cache_key: str | None
    is_cached: bool
    timezone: str | None
    has_more: bool | None = None
    next_allowed_client_refresh: datetime | None = None
    cache_target_age: datetime | None = None
    timings: list[QueryTiming] | None = None
    columns: list | None = None
    query_status: Any | None = None
    hogql: str | None = None
    types: list | None = None


@dataclass(frozen=True)
class NothingInCacheResult(InsightResult):
    result: Any | None = None
    last_refresh: datetime | None = None
    cache_key: str | None = None
    is_cached: bool = False
    timezone: str | None = None
    next_allowed_client_refresh: datetime | None = None
    columns: list | None = None
