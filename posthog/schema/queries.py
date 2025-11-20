# ruff: noqa: F405  # Star imports are intentional
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from posthog.schema.enums import *  # noqa: F403, F401

if TYPE_CHECKING:
    from posthog.schema.filters import *  # noqa: F403, F401
    from posthog.schema.other import *  # noqa: F403, F401


class AssistantHogQLQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["HogQLQuery"] = "HogQLQuery"
    query: str = Field(
        ...,
        description="SQL SELECT statement to execute. Mostly standard ClickHouse SQL with PostHog-specific additions.",
    )


class HogQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bytecode: Optional[list] = None
    coloredBytecode: Optional[list] = None
    results: Any
    stdout: Optional[str] = None


class SuggestedQuestionsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    questions: list[str]


class ExperimentExposureQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_range: DateRange
    kind: Literal["ExperimentExposureQuery"] = "ExperimentExposureQuery"
    timeseries: list[ExperimentExposureTimeSeries]
    total_exposures: dict[str, float]


class HogQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    code: Optional[str] = None
    kind: Literal["HogQuery"] = "HogQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[HogQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsGrossRevenueQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class RevenueAnalyticsMRRQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsMRRQueryResultItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class RevenueAnalyticsMetricsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class RevenueAnalyticsOverviewQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsOverviewItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class RevenueAnalyticsTopCustomersQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class RevenueExampleDataWarehouseTablesQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class RevenueExampleEventsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class SessionAttributionExplorerQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class SessionBatchEventsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    session_events: Optional[list[SessionEventsItem]] = Field(
        default=None, description="Events grouped by session ID. Only populated when group_by_session=True."
    )
    sessions_with_no_events: Optional[list[str]] = Field(
        default=None, description="List of session IDs that had no matching events"
    )
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class SessionsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class SessionsTimelineQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[TimelineEntry]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class StickinessQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class SuggestedQuestionsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["SuggestedQuestionsQuery"] = "SuggestedQuestionsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[SuggestedQuestionsQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class TestBasicQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class TestCachedBasicQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class TraceQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[LLMTrace]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class TracesQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[LLMTrace]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class TrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = Field(default=None, description="Wether more breakdown values are available.")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class UsageMetricsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[UsageMetric]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class WebAnalyticsExternalSummaryQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    data: dict[str, Any]
    error: Optional[ExternalQueryError] = None
    status: ExternalQueryStatus


class WebExternalClicksTableQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class WebGoalsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class WebOverviewQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateFrom: Optional[str] = None
    dateTo: Optional[str] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebOverviewItem]
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    usedPreAggregatedTables: Optional[bool] = None


class WebPageURLSearchQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[PageURL]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class WebStatsTableQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None
    usedPreAggregatedTables: Optional[bool] = None


class ActorsPropertyTaxonomyQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Union[ActorsPropertyTaxonomyResponse, list[ActorsPropertyTaxonomyResponse]]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class ActorsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: int
    missing_actors_count: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: int
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list[str]] = None


class AssistantFunnelsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(
        default=None,
        description=(
            "Use this field to define the aggregation by a specific group from the provided group mapping, which is NOT"
            " users or sessions."
        ),
    )
    breakdownFilter: Optional[AssistantFunnelsBreakdownFilter] = Field(
        default=None,
        description=(
            "A breakdown is used to segment data by a single property value. They divide all defined funnel series into"
            " multiple subseries based on the values of the property. Include a breakdown **only when it is essential"
            " to directly answer the user’s question**. You must not add a breakdown if the question can be addressed"
            " without additional segmentation. When using breakdowns, you must:\n- **Identify the property group** and"
            " name for a breakdown.\n- **Provide the property name** for a breakdown.\n- **Validate that the property"
            " value accurately reflects the intended criteria**. Examples of using a breakdown:\n- page views to sign"
            " up funnel by country: you need to find a property such as `$geoip_country_code` and set it as a"
            " breakdown.\n- conversion rate of users who have completed onboarding after signing up by an organization:"
            " you need to find a property such as `organization name` and set it as a breakdown."
        ),
    )
    dateRange: Optional[Union[AssistantDateRange, AssistantDurationRange]] = Field(
        default=None, description="Date range for the query"
    )
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    funnelsFilter: Optional[AssistantFunnelsFilter] = Field(
        default=None, description="Properties specific to the funnels insight"
    )
    interval: Optional[IntervalType] = Field(
        default=None, description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`"
    )
    kind: Literal["FunnelsQuery"] = "FunnelsQuery"
    properties: Optional[
        list[
            Union[
                Union[
                    AssistantGenericPropertyFilter1,
                    AssistantGenericPropertyFilter2,
                    AssistantGenericPropertyFilter3,
                    AssistantGenericPropertyFilter4,
                    AssistantGenericPropertyFilter5,
                ],
                Union[
                    AssistantGroupPropertyFilter1,
                    AssistantGroupPropertyFilter2,
                    AssistantGroupPropertyFilter3,
                    AssistantGroupPropertyFilter4,
                    AssistantGroupPropertyFilter5,
                ],
            ]
        ]
    ] = Field(default=[], description="Property filters for all series")
    samplingFactor: Optional[float] = Field(
        default=None, description="Sampling rate from 0 to 1 where 1 is 100% of the data."
    )
    series: list[Union[AssistantFunnelsEventsNode, AssistantFunnelsActionsNode]] = Field(
        ..., description="Events or actions to include. Prioritize the more popular and fresh events and actions."
    )


class AssistantRetentionQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[Union[AssistantDateRange, AssistantDurationRange]] = Field(
        default=None, description="Date range for the query"
    )
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    kind: Literal["RetentionQuery"] = "RetentionQuery"
    properties: Optional[
        list[
            Union[
                Union[
                    AssistantGenericPropertyFilter1,
                    AssistantGenericPropertyFilter2,
                    AssistantGenericPropertyFilter3,
                    AssistantGenericPropertyFilter4,
                    AssistantGenericPropertyFilter5,
                ],
                Union[
                    AssistantGroupPropertyFilter1,
                    AssistantGroupPropertyFilter2,
                    AssistantGroupPropertyFilter3,
                    AssistantGroupPropertyFilter4,
                    AssistantGroupPropertyFilter5,
                ],
            ]
        ]
    ] = Field(default=[], description="Property filters for all series")
    retentionFilter: AssistantRetentionFilter = Field(..., description="Properties specific to the retention insight")
    samplingFactor: Optional[float] = Field(
        default=None, description="Sampling rate from 0 to 1 where 1 is 100% of the data."
    )


class AssistantTrendsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdownFilter: Optional[AssistantTrendsBreakdownFilter] = Field(
        default=None,
        description=(
            "Breakdowns are used to segment data by property values of maximum three properties. They divide all"
            " defined trends series to multiple subseries based on the values of the property. Include breakdowns"
            " **only when they are essential to directly answer the user’s question**. You must not add breakdowns if"
            " the question can be addressed without additional segmentation. Always use the minimum set of breakdowns"
            " needed to answer the question. When using breakdowns, you must:\n- **Identify the property group** and"
            " name for each breakdown.\n- **Provide the property name** for each breakdown.\n- **Validate that the"
            " property value accurately reflects the intended criteria**. Examples of using breakdowns:\n- page views"
            " trend by country: you need to find a property such as `$geoip_country_code` and set it as a breakdown.\n-"
            " number of users who have completed onboarding by an organization: you need to find a property such as"
            " `organization name` and set it as a breakdown."
        ),
    )
    compareFilter: Optional[CompareFilter] = Field(default=None, description="Compare to date range")
    dateRange: Optional[Union[AssistantDateRange, AssistantDurationRange]] = Field(
        default=None, description="Date range for the query"
    )
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    interval: Optional[IntervalType] = Field(
        default=IntervalType.DAY,
        description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`",
    )
    kind: Literal["TrendsQuery"] = "TrendsQuery"
    properties: Optional[
        list[
            Union[
                Union[
                    AssistantGenericPropertyFilter1,
                    AssistantGenericPropertyFilter2,
                    AssistantGenericPropertyFilter3,
                    AssistantGenericPropertyFilter4,
                    AssistantGenericPropertyFilter5,
                ],
                Union[
                    AssistantGroupPropertyFilter1,
                    AssistantGroupPropertyFilter2,
                    AssistantGroupPropertyFilter3,
                    AssistantGroupPropertyFilter4,
                    AssistantGroupPropertyFilter5,
                ],
            ]
        ]
    ] = Field(default=[], description="Property filters for all series")
    samplingFactor: Optional[float] = Field(
        default=None, description="Sampling rate from 0 to 1 where 1 is 100% of the data."
    )
    series: list[Union[AssistantTrendsEventsNode, AssistantTrendsActionsNode]] = Field(
        ..., description="Events or actions to include. Prioritize the more popular and fresh events and actions."
    )
    trendsFilter: Optional[AssistantTrendsFilter] = Field(
        default=None, description="Properties specific to the trends insight"
    )


class CachedActorsPropertyTaxonomyQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Union[ActorsPropertyTaxonomyResponse, list[ActorsPropertyTaxonomyResponse]]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedActorsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int
    missing_actors_count: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: int
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list[str]] = None


class CachedCalendarHeatmapQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = Field(default=None, description="Wether more breakdown values are available.")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: EventsHeatMapStructuredResult
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedDocumentSimilarityQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[EmbeddingDistance]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedErrorTrackingBreakdownsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: dict[str, Results]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedErrorTrackingSimilarIssuesQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[SimilarIssue]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedEventTaxonomyQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[EventTaxonomyItem]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedEventsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class CachedExperimentExposureQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    date_range: DateRange
    is_cached: bool
    kind: Literal["ExperimentExposureQuery"] = "ExperimentExposureQuery"
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    timeseries: list[ExperimentExposureTimeSeries]
    timezone: str
    total_exposures: dict[str, float]


class CachedFunnelsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    isUdf: Optional[bool] = None
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedGroupsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    is_cached: bool
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    last_refresh: datetime
    limit: int
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: int
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class CachedLifecycleQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedLogsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedMarketingAnalyticsAggregatedQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: dict[str, MarketingAnalyticsItem]
    samplingRate: Optional[SamplingRate] = None
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedMarketingAnalyticsTableQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list[MarketingAnalyticsItem]]
    samplingRate: Optional[SamplingRate] = None
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class CachedPathsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[PathsLink]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedRevenueAnalyticsGrossRevenueQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedRevenueAnalyticsMRRQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsMRRQueryResultItem]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedRevenueAnalyticsMetricsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedRevenueAnalyticsOverviewQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsOverviewItem]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedRevenueAnalyticsTopCustomersQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedRevenueExampleDataWarehouseTablesQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class CachedRevenueExampleEventsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class CachedSessionAttributionExplorerQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class CachedSessionBatchEventsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    session_events: Optional[list[SessionEventsItem]] = Field(
        default=None, description="Events grouped by session ID. Only populated when group_by_session=True."
    )
    sessions_with_no_events: Optional[list[str]] = Field(
        default=None, description="List of session IDs that had no matching events"
    )
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class CachedSessionsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class CachedSessionsTimelineQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[TimelineEntry]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedStickinessQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedSuggestedQuestionsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    is_cached: bool
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    questions: list[str]
    timezone: str


class CachedTeamTaxonomyQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[TeamTaxonomyItem]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedTraceQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[LLMTrace]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedTracesQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[LLMTrace]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedTrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = Field(default=None, description="Wether more breakdown values are available.")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedUsageMetricsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[UsageMetric]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedVectorSearchQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[VectorSearchResponseItem]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedWebExternalClicksTableQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: Optional[SamplingRate] = None
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class CachedWebGoalsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: Optional[SamplingRate] = None
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class CachedWebOverviewQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    dateFrom: Optional[str] = None
    dateTo: Optional[str] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebOverviewItem]
    samplingRate: Optional[SamplingRate] = None
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    usedPreAggregatedTables: Optional[bool] = None


class CachedWebPageURLSearchQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[PageURL]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedWebStatsTableQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: Optional[SamplingRate] = None
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None
    usedPreAggregatedTables: Optional[bool] = None


class CachedWebVitalsPathBreakdownQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebVitalsPathBreakdownResult] = Field(..., max_length=1, min_length=1)
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class DocumentSimilarityQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[EmbeddingDistance]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class ErrorTrackingBreakdownsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: dict[str, Results]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class ErrorTrackingQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[ErrorTrackingIssue]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class ErrorTrackingSimilarIssuesQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[SimilarIssue]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class EventTaxonomyQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[EventTaxonomyItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class EventsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class FunnelsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    isUdf: Optional[bool] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class GenericCachedQueryResponse(BaseModel):
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    is_cached: bool
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    timezone: str


class GroupsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    limit: int
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: int
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class HogQLQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    clickhouse: Optional[str] = Field(default=None, description="Executed ClickHouse query")
    columns: Optional[list] = Field(default=None, description="Returned columns")
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    explain: Optional[list[str]] = Field(default=None, description="Query explanation output")
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    metadata: Optional[HogQLMetadataResponse] = Field(default=None, description="Query metadata output")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query: Optional[str] = Field(default=None, description="Input query string")
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = Field(default=None, description="Types of returned columns")


class LifecycleQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class LogsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class MarketingAnalyticsAggregatedQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: dict[str, MarketingAnalyticsItem]
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class MarketingAnalyticsTableQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list[MarketingAnalyticsItem]]
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class NewExperimentQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    baseline: ExperimentStatsBaseValidated
    breakdown_results: Optional[list[ExperimentBreakdownResult]] = None
    variant_results: Union[list[ExperimentVariantResultFrequentist], list[ExperimentVariantResultBayesian]]


class PathsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[PathsLink]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class RecordingsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    has_next: bool
    next_cursor: Optional[str] = Field(
        default=None,
        description="Cursor for the next page. Contains the ordering value and session_id from the last record.",
    )
    results: list[SessionRecordingType]


class RevenueAnalyticsBaseQueryRevenueAnalyticsGrossRevenueQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsGrossRevenueQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsBaseQueryRevenueAnalyticsMRRQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsMRRQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsBaseQueryRevenueAnalyticsMetricsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsMetricsQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsBaseQueryRevenueAnalyticsOverviewQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsOverviewQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsBaseQueryRevenueAnalyticsTopCustomersQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsTopCustomersQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsGrossRevenueQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: list[RevenueAnalyticsBreakdown]
    dateRange: Optional[DateRange] = None
    interval: SimpleIntervalType
    kind: Literal["RevenueAnalyticsGrossRevenueQuery"] = "RevenueAnalyticsGrossRevenueQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsGrossRevenueQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsMRRQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: list[RevenueAnalyticsBreakdown]
    dateRange: Optional[DateRange] = None
    interval: SimpleIntervalType
    kind: Literal["RevenueAnalyticsMRRQuery"] = "RevenueAnalyticsMRRQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsMRRQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsMetricsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: list[RevenueAnalyticsBreakdown]
    dateRange: Optional[DateRange] = None
    interval: SimpleIntervalType
    kind: Literal["RevenueAnalyticsMetricsQuery"] = "RevenueAnalyticsMetricsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsMetricsQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsOverviewQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    kind: Literal["RevenueAnalyticsOverviewQuery"] = "RevenueAnalyticsOverviewQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsOverviewQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsTopCustomersQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    groupBy: RevenueAnalyticsTopCustomersGroupBy
    kind: Literal["RevenueAnalyticsTopCustomersQuery"] = "RevenueAnalyticsTopCustomersQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsTopCustomersQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueExampleDataWarehouseTablesQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["RevenueExampleDataWarehouseTablesQuery"] = "RevenueExampleDataWarehouseTablesQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    response: Optional[RevenueExampleDataWarehouseTablesQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueExampleEventsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["RevenueExampleEventsQuery"] = "RevenueExampleEventsQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    response: Optional[RevenueExampleEventsQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class SessionAttributionExplorerQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    filters: Optional[Filters] = None
    groupBy: list[SessionAttributionGroupBy]
    kind: Literal["SessionAttributionExplorerQuery"] = "SessionAttributionExplorerQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    response: Optional[SessionAttributionExplorerQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class SessionsTimelineQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    after: Optional[str] = Field(
        default=None, description="Only fetch sessions that started after this timestamp (default: '-24h')"
    )
    before: Optional[str] = Field(
        default=None, description="Only fetch sessions that started before this timestamp (default: '+5s')"
    )
    kind: Literal["SessionsTimelineQuery"] = "SessionsTimelineQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    personId: Optional[str] = Field(default=None, description="Fetch sessions only for a given person")
    response: Optional[SessionsTimelineQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class TeamTaxonomyQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[TeamTaxonomyItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class TraceQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    kind: Literal["TraceQuery"] = "TraceQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[TraceQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    traceId: str
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class TracesQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    filterTestAccounts: Optional[bool] = None
    groupKey: Optional[str] = None
    groupTypeIndex: Optional[int] = None
    kind: Literal["TracesQuery"] = "TracesQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    personId: Optional[str] = Field(default=None, description="Person who performed the event")
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[TracesQueryResponse] = None
    showColumnConfigurator: Optional[bool] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class UsageMetricsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_key: Optional[str] = Field(
        default=None, description="Group key. Required with group_type_index for group queries."
    )
    group_type_index: Optional[int] = Field(
        default=None, description="Group type index. Required with group_key for group queries."
    )
    kind: Literal["UsageMetricsQuery"] = "UsageMetricsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    person_id: Optional[str] = Field(
        default=None, description="Person ID to fetch metrics for. Mutually exclusive with group parameters."
    )
    response: Optional[UsageMetricsQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class VectorSearchQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[VectorSearchResponseItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class WebAnalyticsExternalSummaryQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange
    kind: Literal["WebAnalyticsExternalSummaryQuery"] = "WebAnalyticsExternalSummaryQuery"
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebAnalyticsExternalSummaryQueryResponse] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class WebExternalClicksTableQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = None
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    filterTestAccounts: Optional[bool] = None
    includeRevenue: Optional[bool] = None
    kind: Literal["WebExternalClicksTableQuery"] = "WebExternalClicksTableQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    orderBy: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebExternalClicksTableQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    stripQueryParams: Optional[bool] = None
    tags: Optional[QueryLogTags] = None
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class WebGoalsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = None
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    filterTestAccounts: Optional[bool] = None
    includeRevenue: Optional[bool] = None
    kind: Literal["WebGoalsQuery"] = "WebGoalsQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    orderBy: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebGoalsQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    tags: Optional[QueryLogTags] = None
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class WebOverviewQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = None
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    filterTestAccounts: Optional[bool] = None
    includeRevenue: Optional[bool] = None
    kind: Literal["WebOverviewQuery"] = "WebOverviewQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    orderBy: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebOverviewQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    tags: Optional[QueryLogTags] = None
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class WebPageURLSearchQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = None
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    filterTestAccounts: Optional[bool] = None
    includeRevenue: Optional[bool] = None
    kind: Literal["WebPageURLSearchQuery"] = "WebPageURLSearchQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    orderBy: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebPageURLSearchQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    searchTerm: Optional[str] = None
    stripQueryParams: Optional[bool] = None
    tags: Optional[QueryLogTags] = None
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class WebStatsTableQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdownBy: WebStatsBreakdown
    compareFilter: Optional[CompareFilter] = None
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    filterTestAccounts: Optional[bool] = None
    includeBounceRate: Optional[bool] = None
    includeRevenue: Optional[bool] = None
    includeScrollDepth: Optional[bool] = None
    kind: Literal["WebStatsTableQuery"] = "WebStatsTableQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    orderBy: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebStatsTableQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    tags: Optional[QueryLogTags] = None
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class WebTrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    clickhouse: Optional[str] = Field(default=None, description="Executed ClickHouse query")
    columns: Optional[list] = Field(default=None, description="Returned columns")
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    explain: Optional[list[str]] = Field(default=None, description="Query explanation output")
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    metadata: Optional[HogQLMetadataResponse] = Field(default=None, description="Query metadata output")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query: Optional[str] = Field(default=None, description="Input query string")
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebTrendsItem]
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = Field(default=None, description="Types of returned columns")
    usedPreAggregatedTables: Optional[bool] = None


class WebVitalsPathBreakdownQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebVitalsPathBreakdownResult] = Field(..., max_length=1, min_length=1)
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class WebVitalsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebVitalsItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class ActorsPropertyTaxonomyQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    groupTypeIndex: Optional[int] = None
    kind: Literal["ActorsPropertyTaxonomyQuery"] = "ActorsPropertyTaxonomyQuery"
    maxPropertyValues: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[str]
    response: Optional[ActorsPropertyTaxonomyQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class CachedErrorTrackingQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[ErrorTrackingIssue]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedHogQLQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    clickhouse: Optional[str] = Field(default=None, description="Executed ClickHouse query")
    columns: Optional[list] = Field(default=None, description="Returned columns")
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    explain: Optional[list[str]] = Field(default=None, description="Query explanation output")
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    metadata: Optional[HogQLMetadataResponse] = Field(default=None, description="Query metadata output")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query: Optional[str] = Field(default=None, description="Input query string")
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = Field(default=None, description="Types of returned columns")


class CachedNewExperimentQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    baseline: ExperimentStatsBaseValidated
    breakdown_results: Optional[list[ExperimentBreakdownResult]] = None
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    is_cached: bool
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    timezone: str
    variant_results: Union[list[ExperimentVariantResultFrequentist], list[ExperimentVariantResultBayesian]]


class CachedRetentionQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RetentionResult]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedWebTrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    clickhouse: Optional[str] = Field(default=None, description="Executed ClickHouse query")
    columns: Optional[list] = Field(default=None, description="Returned columns")
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    explain: Optional[list[str]] = Field(default=None, description="Query explanation output")
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    metadata: Optional[HogQLMetadataResponse] = Field(default=None, description="Query metadata output")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query: Optional[str] = Field(default=None, description="Input query string")
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebTrendsItem]
    samplingRate: Optional[SamplingRate] = None
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = Field(default=None, description="Types of returned columns")
    usedPreAggregatedTables: Optional[bool] = None


class CachedWebVitalsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebVitalsItem]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class DocumentSimilarityQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange
    distance_func: DistanceFunc
    document_types: list[str]
    kind: Literal["DocumentSimilarityQuery"] = "DocumentSimilarityQuery"
    limit: Optional[int] = None
    model: str
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    order_by: OrderBy
    order_direction: OrderDirection
    origin: EmbeddedDocument
    products: list[str]
    renderings: list[str]
    response: Optional[DocumentSimilarityQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    threshold: Optional[float] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class ErrorTrackingBreakdownsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdownProperties: list[str]
    dateRange: Optional[DateRange] = None
    filterTestAccounts: Optional[bool] = None
    issueId: str
    kind: Literal["ErrorTrackingBreakdownsQuery"] = "ErrorTrackingBreakdownsQuery"
    maxValuesPerProperty: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[ErrorTrackingBreakdownsQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class ErrorTrackingIssueCorrelationQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[ErrorTrackingCorrelatedIssue]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class ErrorTrackingSimilarIssuesQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    issueId: str
    kind: Literal["ErrorTrackingSimilarIssuesQuery"] = "ErrorTrackingSimilarIssuesQuery"
    limit: Optional[int] = None
    maxDistance: Optional[float] = None
    modelName: Optional[EmbeddingModelName] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    rendering: Optional[str] = None
    response: Optional[ErrorTrackingSimilarIssuesQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class EventTaxonomyQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    actionId: Optional[int] = None
    event: Optional[str] = None
    kind: Literal["EventTaxonomyQuery"] = "EventTaxonomyQuery"
    maxPropertyValues: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[list[str]] = None
    response: Optional[EventTaxonomyQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class GroupsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: int
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    orderBy: Optional[list[str]] = None
    properties: Optional[list[Union[GroupPropertyFilter, HogQLPropertyFilter]]] = None
    response: Optional[GroupsQueryResponse] = None
    search: Optional[str] = None
    select: Optional[list[str]] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class HogQLASTQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    explain: Optional[bool] = None
    filters: Optional[HogQLFilters] = None
    kind: Literal["HogQLASTQuery"] = "HogQLASTQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    name: Optional[str] = Field(default=None, description="Client provided name of the query")
    query: dict[str, Any]
    response: Optional[HogQLQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    values: Optional[dict[str, Any]] = Field(
        default=None, description="Constant values that can be referenced with the {placeholder} syntax in the query"
    )
    variables: Optional[dict[str, HogQLVariable]] = Field(
        default=None, description="Variables to be substituted into the query"
    )
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class HogQLQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    explain: Optional[bool] = None
    filters: Optional[HogQLFilters] = None
    kind: Literal["HogQLQuery"] = "HogQLQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    name: Optional[str] = Field(default=None, description="Client provided name of the query")
    query: str
    response: Optional[HogQLQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    values: Optional[dict[str, Any]] = Field(
        default=None, description="Constant values that can be referenced with the {placeholder} syntax in the query"
    )
    variables: Optional[dict[str, HogQLVariable]] = Field(
        default=None, description="Variables to be substituted into the query"
    )
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class MarketingAnalyticsAggregatedQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = None
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    draftConversionGoal: Optional[Union[ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3]] = Field(
        default=None, description="Draft conversion goal that can be set in the UI without saving"
    )
    filterTestAccounts: Optional[bool] = None
    includeRevenue: Optional[bool] = None
    integrationFilter: Optional[IntegrationFilter] = Field(default=None, description="Filter by integration IDs")
    kind: Literal["MarketingAnalyticsAggregatedQuery"] = "MarketingAnalyticsAggregatedQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[MarketingAnalyticsAggregatedQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    select: Optional[list[str]] = Field(
        default=None, description="Return a limited set of data. Will use default columns if empty."
    )
    tags: Optional[QueryLogTags] = None
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class MarketingAnalyticsTableQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = Field(default=None, description="Compare to date range")
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    draftConversionGoal: Optional[Union[ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3]] = Field(
        default=None, description="Draft conversion goal that can be set in the UI without saving"
    )
    filterTestAccounts: Optional[bool] = Field(default=None, description="Filter test accounts")
    includeAllConversions: Optional[bool] = Field(
        default=None, description="Include conversion goal rows even when they don't match campaign costs table"
    )
    includeRevenue: Optional[bool] = None
    integrationFilter: Optional[IntegrationFilter] = Field(default=None, description="Filter by integration type")
    kind: Literal["MarketingAnalyticsTableQuery"] = "MarketingAnalyticsTableQuery"
    limit: Optional[int] = Field(default=None, description="Number of rows to return")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = Field(default=None, description="Number of rows to skip before returning rows")
    orderBy: Optional[list[list[Union[str, MarketingAnalyticsOrderByEnum]]]] = Field(
        default=None, description="Columns to order by - similar to EventsQuery format"
    )
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[MarketingAnalyticsTableQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    select: Optional[list[str]] = Field(
        default=None, description="Return a limited set of data. Will use default columns if empty."
    )
    tags: Optional[QueryLogTags] = None
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RecordingsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    actions: Optional[list[dict[str, Any]]] = None
    after: Optional[str] = Field(
        default=None,
        description=(
            "Cursor for pagination. Contains the ordering value and session_id from the last record of the previous"
            " page."
        ),
    )
    comment_text: Optional[RecordingPropertyFilter] = None
    console_log_filters: Optional[list[LogEntryPropertyFilter]] = None
    date_from: Optional[str] = "-3d"
    date_to: Optional[str] = None
    distinct_ids: Optional[list[str]] = None
    events: Optional[list[dict[str, Any]]] = None
    filter_test_accounts: Optional[bool] = None
    having_predicates: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = None
    kind: Literal["RecordingsQuery"] = "RecordingsQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    operand: Optional[FilterLogicalOperator] = FilterLogicalOperator.AND_
    order: Optional[RecordingOrder] = RecordingOrder.START_TIME
    order_direction: Optional[RecordingOrderDirection] = Field(
        default=RecordingOrderDirection.DESC,
        description=(
            "Replay originally had all ordering as descending by specifying the field name, this runs counter to Django"
            " behavior where the field name specifies ascending sorting (e.g. the_field_name) and -the_field_name would"
            " indicate descending order to avoid invalidating or migrating all existing filters we keep DESC as the"
            " default or allow specification of an explicit order direction here"
        ),
    )
    person_uuid: Optional[str] = None
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = None
    response: Optional[RecordingsQueryResponse] = None
    session_ids: Optional[list[str]] = None
    session_recording_id: Optional[str] = Field(
        default=None,
        description=(
            "If provided, this recording will be fetched and prepended to the results, even if it doesn't match the"
            " filters"
        ),
    )
    tags: Optional[QueryLogTags] = None
    user_modified_filters: Optional[dict[str, Any]] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RetentionQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RetentionResult]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class StickinessQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = Field(default=None, description="Compare to date range")
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    interval: Optional[IntervalType] = Field(
        default=IntervalType.DAY,
        description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`",
    )
    intervalCount: Optional[int] = Field(
        default=None, description="How many intervals comprise a period. Only used for cohorts, otherwise default 1."
    )
    kind: Literal["StickinessQuery"] = "StickinessQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    EventMetadataPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    LogEntryPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    FlagPropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                    ErrorTrackingIssueFilter,
                    LogPropertyFilter,
                    RevenueAnalyticsPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[StickinessQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )
    stickinessFilter: Optional[StickinessFilter] = Field(
        default=None, description="Properties specific to the stickiness insight"
    )
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class TeamTaxonomyQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["TeamTaxonomyQuery"] = "TeamTaxonomyQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[TeamTaxonomyQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class TrendsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    breakdownFilter: Optional[BreakdownFilter] = Field(default=None, description="Breakdown of the events and actions")
    compareFilter: Optional[CompareFilter] = Field(default=None, description="Compare to date range")
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = Field(
        default=None, description="Whether we should be comparing against a specific conversion goal"
    )
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    interval: Optional[IntervalType] = Field(
        default=IntervalType.DAY,
        description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`",
    )
    kind: Literal["TrendsQuery"] = "TrendsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    EventMetadataPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    LogEntryPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    FlagPropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                    ErrorTrackingIssueFilter,
                    LogPropertyFilter,
                    RevenueAnalyticsPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[TrendsQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    trendsFilter: Optional[TrendsFilter] = Field(default=None, description="Properties specific to the trends insight")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class VectorSearchQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    embedding: list[float]
    embeddingVersion: Optional[float] = None
    kind: Literal["VectorSearchQuery"] = "VectorSearchQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[VectorSearchQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class WebTrendsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = None
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    filterTestAccounts: Optional[bool] = None
    includeRevenue: Optional[bool] = None
    interval: IntervalType
    kind: Literal["WebTrendsQuery"] = "WebTrendsQuery"
    limit: Optional[int] = None
    metrics: list[WebTrendsMetric]
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    orderBy: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebTrendsQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    tags: Optional[QueryLogTags] = None
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class WebVitalsPathBreakdownQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = None
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    filterTestAccounts: Optional[bool] = None
    includeRevenue: Optional[bool] = None
    kind: Literal["WebVitalsPathBreakdownQuery"] = "WebVitalsPathBreakdownQuery"
    metric: WebVitalsMetric
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    orderBy: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None
    percentile: WebVitalsPercentile
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebVitalsPathBreakdownQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    tags: Optional[QueryLogTags] = None
    thresholds: list[float] = Field(..., max_length=2, min_length=2)
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class CachedErrorTrackingIssueCorrelationQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[ErrorTrackingCorrelatedIssue]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedExperimentTrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    count_query: Optional[TrendsQuery] = None
    credible_intervals: dict[str, list[float]]
    exposure_query: Optional[TrendsQuery] = None
    insight: list[dict[str, Any]]
    is_cached: bool
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    p_value: float
    probability: dict[str, float]
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: Optional[int] = None
    timezone: str
    variants: list[ExperimentVariantTrendsBaseStats]


class CalendarHeatmapQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    calendarHeatmapFilter: Optional[CalendarHeatmapFilter] = Field(
        default=None, description="Properties specific to the trends insight"
    )
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = Field(
        default=None, description="Whether we should be comparing against a specific conversion goal"
    )
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    interval: Optional[IntervalType] = Field(
        default=IntervalType.DAY,
        description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`",
    )
    kind: Literal["CalendarHeatmapQuery"] = "CalendarHeatmapQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    EventMetadataPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    LogEntryPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    FlagPropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                    ErrorTrackingIssueFilter,
                    LogPropertyFilter,
                    RevenueAnalyticsPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[CalendarHeatmapResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class ErrorTrackingIssueCorrelationQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    events: list[str]
    kind: Literal["ErrorTrackingIssueCorrelationQuery"] = "ErrorTrackingIssueCorrelationQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[ErrorTrackingIssueCorrelationQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class ErrorTrackingQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    assignee: Optional[ErrorTrackingIssueAssignee] = None
    dateRange: DateRange
    filterGroup: Optional[PropertyGroupFilter] = None
    filterTestAccounts: Optional[bool] = None
    groupKey: Optional[str] = None
    groupTypeIndex: Optional[int] = None
    issueId: Optional[str] = None
    kind: Literal["ErrorTrackingQuery"] = "ErrorTrackingQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    orderBy: OrderBy1
    orderDirection: Optional[OrderDirection1] = None
    personId: Optional[str] = None
    response: Optional[ErrorTrackingQueryResponse] = None
    revenueEntity: Optional[RevenueEntity] = None
    revenuePeriod: Optional[RevenuePeriod] = None
    searchQuery: Optional[str] = None
    status: Optional[Status2] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")
    volumeResolution: int
    withAggregations: Optional[bool] = None
    withFirstEvent: Optional[bool] = None
    withLastEvent: Optional[bool] = None


class ExperimentExposureQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    end_date: Optional[str] = None
    experiment_id: Optional[int] = None
    experiment_name: str
    exposure_criteria: Optional[ExperimentExposureCriteria] = None
    feature_flag: dict[str, Any]
    holdout: Optional[ExperimentHoldoutType] = None
    kind: Literal["ExperimentExposureQuery"] = "ExperimentExposureQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[ExperimentExposureQueryResponse] = None
    start_date: Optional[str] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class ExperimentQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    baseline: Optional[ExperimentStatsBaseValidated] = None
    breakdown_results: Optional[list[ExperimentBreakdownResult]] = Field(
        default=None,
        description=(
            "Results grouped by breakdown value. When present, baseline and variant_results contain aggregated data."
        ),
    )
    credible_intervals: Optional[dict[str, list[float]]] = None
    insight: Optional[list[dict[str, Any]]] = None
    kind: Literal["ExperimentQuery"] = "ExperimentQuery"
    metric: Optional[Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]] = None
    p_value: Optional[float] = None
    probability: Optional[dict[str, float]] = None
    significance_code: Optional[ExperimentSignificanceCode] = None
    significant: Optional[bool] = None
    stats_version: Optional[int] = None
    variant_results: Optional[
        Union[list[ExperimentVariantResultFrequentist], list[ExperimentVariantResultBayesian]]
    ] = None
    variants: Optional[Union[list[ExperimentVariantTrendsBaseStats], list[ExperimentVariantFunnelsBaseStats]]] = None


class ExperimentTrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count_query: Optional[TrendsQuery] = None
    credible_intervals: dict[str, list[float]]
    exposure_query: Optional[TrendsQuery] = None
    insight: list[dict[str, Any]]
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    p_value: float
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: Optional[int] = None
    variants: list[ExperimentVariantTrendsBaseStats]


class FunnelsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    breakdownFilter: Optional[BreakdownFilter] = Field(default=None, description="Breakdown of the events and actions")
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    funnelsFilter: Optional[FunnelsFilter] = Field(
        default=None, description="Properties specific to the funnels insight"
    )
    interval: Optional[IntervalType] = Field(
        default=None, description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`"
    )
    kind: Literal["FunnelsQuery"] = "FunnelsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    EventMetadataPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    LogEntryPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    FlagPropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                    ErrorTrackingIssueFilter,
                    LogPropertyFilter,
                    RevenueAnalyticsPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[FunnelsQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class InsightsQueryBaseFunnelsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    EventMetadataPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    LogEntryPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    FlagPropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                    ErrorTrackingIssueFilter,
                    LogPropertyFilter,
                    RevenueAnalyticsPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[FunnelsQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class InsightsQueryBaseLifecycleQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    EventMetadataPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    LogEntryPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    FlagPropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                    ErrorTrackingIssueFilter,
                    LogPropertyFilter,
                    RevenueAnalyticsPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[LifecycleQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class InsightsQueryBasePathsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    EventMetadataPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    LogEntryPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    FlagPropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                    ErrorTrackingIssueFilter,
                    LogPropertyFilter,
                    RevenueAnalyticsPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[PathsQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class InsightsQueryBaseRetentionQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    EventMetadataPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    LogEntryPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    FlagPropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                    ErrorTrackingIssueFilter,
                    LogPropertyFilter,
                    RevenueAnalyticsPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[RetentionQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class InsightsQueryBaseTrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    EventMetadataPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    LogEntryPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    FlagPropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                    ErrorTrackingIssueFilter,
                    LogPropertyFilter,
                    RevenueAnalyticsPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[TrendsQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class LegacyExperimentQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    credible_intervals: dict[str, list[float]]
    insight: list[dict[str, Any]]
    kind: Literal["ExperimentQuery"] = "ExperimentQuery"
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]
    p_value: float
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: Optional[int] = None
    variants: Union[list[ExperimentVariantTrendsBaseStats], list[ExperimentVariantFunnelsBaseStats]]


class LifecycleQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    interval: Optional[IntervalType] = Field(
        default=IntervalType.DAY,
        description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`",
    )
    kind: Literal["LifecycleQuery"] = "LifecycleQuery"
    lifecycleFilter: Optional[LifecycleFilter] = Field(
        default=None, description="Properties specific to the lifecycle insight"
    )
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    EventMetadataPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    LogEntryPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    FlagPropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                    ErrorTrackingIssueFilter,
                    LogPropertyFilter,
                    RevenueAnalyticsPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[LifecycleQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class LogsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange
    filterGroup: PropertyGroupFilter
    kind: Literal["LogsQuery"] = "LogsQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    orderBy: Optional[OrderBy3] = None
    response: Optional[LogsQueryResponse] = None
    searchTerm: Optional[str] = None
    serviceNames: list[str]
    severityLevels: list[LogSeverityLevel]
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RetentionQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    breakdownFilter: Optional[BreakdownFilter] = Field(default=None, description="Breakdown of the events and actions")
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    kind: Literal["RetentionQuery"] = "RetentionQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    EventMetadataPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    LogEntryPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    FlagPropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                    ErrorTrackingIssueFilter,
                    LogPropertyFilter,
                    RevenueAnalyticsPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[RetentionQueryResponse] = None
    retentionFilter: RetentionFilter = Field(..., description="Properties specific to the retention insight")
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class SessionsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    after: Optional[str] = Field(default=None, description="Only fetch sessions that started after this timestamp")
    before: Optional[str] = Field(default=None, description="Only fetch sessions that started before this timestamp")
    filterTestAccounts: Optional[bool] = Field(default=None, description="Filter test accounts")
    fixedProperties: Optional[
        list[
            Union[
                PropertyGroupFilter,
                PropertyGroupFilterValue,
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    EventMetadataPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    LogEntryPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    FlagPropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                    ErrorTrackingIssueFilter,
                    LogPropertyFilter,
                    RevenueAnalyticsPropertyFilter,
                ],
            ]
        ]
    ] = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    kind: Literal["SessionsQuery"] = "SessionsQuery"
    limit: Optional[int] = Field(default=None, description="Number of rows to return")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = Field(default=None, description="Number of rows to skip before returning rows")
    orderBy: Optional[list[str]] = Field(default=None, description="Columns to order by")
    personId: Optional[str] = Field(default=None, description="Show sessions for a given person")
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[SessionsQueryResponse] = None
    select: list[str] = Field(..., description="Return a limited set of data. Required.")
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")
    where: Optional[list[str]] = Field(default=None, description="HogQL filters to apply on returned data")


class StickinessActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compare: Optional[Compare] = None
    day: Optional[Union[str, int]] = None
    includeRecordings: Optional[bool] = None
    kind: Literal["StickinessActorsQuery"] = "StickinessActorsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    operator: Optional[StickinessOperator] = None
    response: Optional[ActorsQueryResponse] = None
    series: Optional[int] = None
    source: StickinessQuery
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class CachedExperimentFunnelsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    credible_intervals: dict[str, list[float]]
    expected_loss: float
    funnels_query: Optional[FunnelsQuery] = None
    insight: list[list[dict[str, Any]]]
    is_cached: bool
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    probability: dict[str, float]
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: Optional[int] = None
    timezone: str
    variants: list[ExperimentVariantFunnelsBaseStats]


class CachedExperimentQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    baseline: Optional[ExperimentStatsBaseValidated] = None
    breakdown_results: Optional[list[ExperimentBreakdownResult]] = Field(
        default=None,
        description=(
            "Results grouped by breakdown value. When present, baseline and variant_results contain aggregated data."
        ),
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    credible_intervals: Optional[dict[str, list[float]]] = None
    insight: Optional[list[dict[str, Any]]] = None
    is_cached: bool
    kind: Literal["ExperimentQuery"] = "ExperimentQuery"
    last_refresh: datetime
    metric: Optional[Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]] = None
    next_allowed_client_refresh: datetime
    p_value: Optional[float] = None
    probability: Optional[dict[str, float]] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    significance_code: Optional[ExperimentSignificanceCode] = None
    significant: Optional[bool] = None
    stats_version: Optional[int] = None
    timezone: str
    variant_results: Optional[
        Union[list[ExperimentVariantResultFrequentist], list[ExperimentVariantResultBayesian]]
    ] = None
    variants: Optional[Union[list[ExperimentVariantTrendsBaseStats], list[ExperimentVariantFunnelsBaseStats]]] = None


class CachedLegacyExperimentQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    credible_intervals: dict[str, list[float]]
    insight: list[dict[str, Any]]
    is_cached: bool
    kind: Literal["ExperimentQuery"] = "ExperimentQuery"
    last_refresh: datetime
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]
    next_allowed_client_refresh: datetime
    p_value: float
    probability: dict[str, float]
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: Optional[int] = None
    timezone: str
    variants: Union[list[ExperimentVariantTrendsBaseStats], list[ExperimentVariantFunnelsBaseStats]]


class ExperimentFunnelsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    credible_intervals: dict[str, list[float]]
    expected_loss: float
    funnels_query: Optional[FunnelsQuery] = None
    insight: list[list[dict[str, Any]]]
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: Optional[int] = None
    variants: list[ExperimentVariantFunnelsBaseStats]


class ExperimentQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    experiment_id: Optional[int] = None
    kind: Literal["ExperimentQuery"] = "ExperimentQuery"
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    name: Optional[str] = None
    response: Optional[ExperimentQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class ExperimentTrendsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count_query: TrendsQuery
    experiment_id: Optional[int] = None
    exposure_query: Optional[TrendsQuery] = None
    fingerprint: Optional[str] = None
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    name: Optional[str] = None
    response: Optional[ExperimentTrendsQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    uuid: Optional[str] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class FunnelsActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnelStep: Optional[int] = Field(
        default=None,
        description=(
            "Index of the step for which we want to get the timestamp for, per person. Positive for converted persons,"
            " negative for dropped of persons."
        ),
    )
    funnelStepBreakdown: Optional[Union[int, str, float, list[Union[int, str, float]]]] = Field(
        default=None,
        description=(
            "The breakdown value for which to get persons for. This is an array for person and event properties, a"
            " string for groups and an integer for cohorts."
        ),
    )
    funnelTrendsDropOff: Optional[bool] = None
    funnelTrendsEntrancePeriodStart: Optional[str] = Field(
        default=None,
        description="Used together with `funnelTrendsDropOff` for funnels time conversion date for the persons modal.",
    )
    includeRecordings: Optional[bool] = None
    kind: Literal["FunnelsActorsQuery"] = "FunnelsActorsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[ActorsQueryResponse] = None
    source: FunnelsQuery
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class PathsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    funnelPathsFilter: Optional[FunnelPathsFilter] = Field(
        default=None, description="Used for displaying paths in relation to funnel steps."
    )
    kind: Literal["PathsQuery"] = "PathsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    pathsFilter: PathsFilter = Field(..., description="Properties specific to the paths insight")
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    EventMetadataPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    LogEntryPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    FlagPropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                    ErrorTrackingIssueFilter,
                    LogPropertyFilter,
                    RevenueAnalyticsPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[PathsQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class DatabaseSchemaQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    joins: list[DataWarehouseViewLink]
    tables: dict[
        str,
        Union[
            DatabaseSchemaPostHogTable,
            DatabaseSchemaSystemTable,
            DatabaseSchemaDataWarehouseTable,
            DatabaseSchemaViewTable,
            DatabaseSchemaManagedViewTable,
            DatabaseSchemaBatchExportTable,
            DatabaseSchemaMaterializedViewTable,
            DatabaseSchemaEndpointTable,
        ],
    ]


class ExperimentFunnelsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    experiment_id: Optional[int] = None
    fingerprint: Optional[str] = None
    funnels_query: FunnelsQuery
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    name: Optional[str] = None
    response: Optional[ExperimentFunnelsQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    uuid: Optional[str] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class FunnelCorrelationQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnelCorrelationEventExcludePropertyNames: Optional[list[str]] = None
    funnelCorrelationEventNames: Optional[list[str]] = None
    funnelCorrelationExcludeEventNames: Optional[list[str]] = None
    funnelCorrelationExcludeNames: Optional[list[str]] = None
    funnelCorrelationNames: Optional[list[str]] = None
    funnelCorrelationType: FunnelCorrelationResultsType
    kind: Literal["FunnelCorrelationQuery"] = "FunnelCorrelationQuery"
    response: Optional[FunnelCorrelationResponse] = None
    source: FunnelsActorsQuery
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class WebVitalsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = None
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    filterTestAccounts: Optional[bool] = None
    includeRevenue: Optional[bool] = None
    kind: Literal["WebVitalsQuery"] = "WebVitalsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    orderBy: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebGoalsQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    source: Union[TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, StickinessQuery, LifecycleQuery] = Field(
        ..., discriminator="kind"
    )
    tags: Optional[QueryLogTags] = None
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class DatabaseSchemaQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["DatabaseSchemaQuery"] = "DatabaseSchemaQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[DatabaseSchemaQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class FunnelCorrelationActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnelCorrelationPersonConverted: Optional[bool] = None
    funnelCorrelationPersonEntity: Optional[Union[EventsNode, ActionsNode, DataWarehouseNode]] = None
    funnelCorrelationPropertyValues: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = None
    includeRecordings: Optional[bool] = None
    kind: Literal["FunnelCorrelationActorsQuery"] = "FunnelCorrelationActorsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[ActorsQueryResponse] = None
    source: FunnelCorrelationQuery
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class InsightActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: Optional[Union[str, list[str], int]] = None
    compare: Optional[Compare] = None
    day: Optional[Union[str, int]] = None
    includeRecordings: Optional[bool] = None
    interval: Optional[int] = Field(
        default=None, description="An interval selected out of available intervals in source query."
    )
    kind: Literal["InsightActorsQuery"] = "InsightActorsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[ActorsQueryResponse] = None
    series: Optional[int] = None
    source: Union[TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, StickinessQuery, LifecycleQuery] = Field(
        ..., discriminator="kind"
    )
    status: Optional[str] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class SessionBatchEventsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    actionId: Optional[int] = Field(default=None, description="Show events matching a given action")
    after: Optional[str] = Field(default=None, description="Only fetch events that happened after this timestamp")
    before: Optional[str] = Field(default=None, description="Only fetch events that happened before this timestamp")
    event: Optional[str] = Field(default=None, description="Limit to events matching this string")
    filterTestAccounts: Optional[bool] = Field(default=None, description="Filter test accounts")
    fixedProperties: Optional[
        list[
            Union[
                PropertyGroupFilter,
                PropertyGroupFilterValue,
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    EventMetadataPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    LogEntryPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    FlagPropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                    ErrorTrackingIssueFilter,
                    LogPropertyFilter,
                    RevenueAnalyticsPropertyFilter,
                ],
            ]
        ]
    ] = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    group_by_session: Optional[bool] = Field(
        default=None, description="Whether to group results by session_id in the response"
    )
    kind: Literal["SessionBatchEventsQuery"] = "SessionBatchEventsQuery"
    limit: Optional[int] = Field(default=None, description="Number of rows to return")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = Field(default=None, description="Number of rows to skip before returning rows")
    orderBy: Optional[list[str]] = Field(default=None, description="Columns to order by")
    personId: Optional[str] = Field(default=None, description="Show events for a given person")
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[SessionBatchEventsQueryResponse] = None
    select: list[str] = Field(..., description="Return a limited set of data. Required.")
    session_ids: list[str] = Field(
        ..., description="List of session IDs to fetch events for. Will be translated to $session_id IN filter."
    )
    source: Optional[InsightActorsQuery] = Field(default=None, description="source for querying events for insights")
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")
    where: Optional[list[str]] = Field(default=None, description="HogQL filters to apply on returned data")


class ActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fixedProperties: Optional[
        list[Union[PersonPropertyFilter, CohortPropertyFilter, HogQLPropertyFilter, EmptyPropertyFilter]]
    ] = Field(
        default=None,
        description=(
            "Currently only person filters supported. No filters for querying groups. See `filter_conditions()` in"
            " actor_strategies.py."
        ),
    )
    kind: Literal["ActorsQuery"] = "ActorsQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    orderBy: Optional[list[str]] = None
    properties: Optional[
        Union[
            list[Union[PersonPropertyFilter, CohortPropertyFilter, HogQLPropertyFilter, EmptyPropertyFilter]],
            PropertyGroupFilterValue,
        ]
    ] = Field(
        default=None,
        description=(
            "Currently only person filters supported. No filters for querying groups. See `filter_conditions()` in"
            " actor_strategies.py."
        ),
    )
    response: Optional[ActorsQueryResponse] = None
    search: Optional[str] = None
    select: Optional[list[str]] = None
    source: Optional[
        Union[InsightActorsQuery, FunnelsActorsQuery, FunnelCorrelationActorsQuery, StickinessActorsQuery, HogQLQuery]
    ] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class EventsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    actionId: Optional[int] = Field(default=None, description="Show events matching a given action")
    after: Optional[str] = Field(default=None, description="Only fetch events that happened after this timestamp")
    before: Optional[str] = Field(default=None, description="Only fetch events that happened before this timestamp")
    event: Optional[str] = Field(default=None, description="Limit to events matching this string")
    filterTestAccounts: Optional[bool] = Field(default=None, description="Filter test accounts")
    fixedProperties: Optional[
        list[
            Union[
                PropertyGroupFilter,
                PropertyGroupFilterValue,
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    EventMetadataPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    LogEntryPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    FlagPropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                    ErrorTrackingIssueFilter,
                    LogPropertyFilter,
                    RevenueAnalyticsPropertyFilter,
                ],
            ]
        ]
    ] = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    kind: Literal["EventsQuery"] = "EventsQuery"
    limit: Optional[int] = Field(default=None, description="Number of rows to return")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = Field(default=None, description="Number of rows to skip before returning rows")
    orderBy: Optional[list[str]] = Field(default=None, description="Columns to order by")
    personId: Optional[str] = Field(default=None, description="Show events for a given person")
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[EventsQueryResponse] = None
    select: list[str] = Field(..., description="Return a limited set of data. Required.")
    source: Optional[InsightActorsQuery] = Field(default=None, description="source for querying events for insights")
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")
    where: Optional[list[str]] = Field(default=None, description="HogQL filters to apply on returned data")
