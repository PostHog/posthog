from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Optional

from posthog.schema import QueryTiming


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


class InsightResultStatus(StrEnum):
    """Why an insight result holds what it holds. `result` alone cannot say this: a null result
    reads the same whether the query returned no rows, nothing was cached, or the query failed."""

    OK = "ok"
    CACHE_MISS = "cache_miss"
    QUERY_PENDING = "query_pending"
    ERROR = "error"


def insight_result_status(result: InsightResult) -> InsightResultStatus:
    query_status = result.query_status or {}
    if query_status.get("error"):
        return InsightResultStatus.ERROR
    if result.result is None and query_status and not query_status.get("complete"):
        # `refresh=force_async` skips the cache and returns no result, so it is not a cache miss
        # and the pending status has to be read first. A result that is present stays `ok`,
        # because a stale cached answer is still an answer while a recalculation runs behind it.
        return InsightResultStatus.QUERY_PENDING
    if not isinstance(result, NothingInCacheResult):
        return InsightResultStatus.OK
    return InsightResultStatus.CACHE_MISS
