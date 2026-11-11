from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Self

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
    # ResolvedDateRangeResponse-shaped dicts — the fields carry model_dump output
    resolved_date_range: Optional[dict] = None
    resolved_compare_date_range: Optional[dict] = None
    action_names: Optional[dict[str, str]] = None
    # A QueryScanSummary dict. The insight serializer puts the stored analysis on it.
    query_scan: Optional[dict] = None
    warnings: Optional[list] = None

    @classmethod
    def from_response_dict(cls, response: dict[str, Any]) -> Self:
        return cls(
            # Translating `QueryResponse` to legacy insights shape
            # The response may not be conformant with that, hence these are all `.get()`s
            result=response.get("results"),
            has_more=response.get("hasMore"),
            columns=response.get("columns"),
            last_refresh=response.get("last_refresh"),
            cache_key=response.get("cache_key"),
            is_cached=response.get("is_cached", False),
            timezone=response.get("timezone"),
            next_allowed_client_refresh=response.get("next_allowed_client_refresh"),
            cache_target_age=response.get("cache_target_age"),
            timings=response.get("timings"),
            query_status=response.get("query_status"),
            hogql=response.get("hogql"),
            types=response.get("types"),
            resolved_date_range=response.get("resolved_date_range"),
            resolved_compare_date_range=response.get("resolved_compare_date_range"),
            action_names=response.get("action_names"),
            query_scan=response.get("query_scan"),
            warnings=response.get("warnings"),
        )


@dataclass(frozen=True)
class NothingInCacheResult(InsightResult):
    result: Optional[Any] = None
    last_refresh: Optional[datetime] = None
    cache_key: Optional[str] = None
    is_cached: bool = False
    timezone: Optional[str] = None
    next_allowed_client_refresh: Optional[datetime] = None
    columns: Optional[list] = None
