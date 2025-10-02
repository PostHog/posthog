from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from time import perf_counter
from types import UnionType
from typing import Any, Generic, Optional, Protocol, TypeGuard, TypeVar, Union, cast, get_args

import structlog
import posthoganalytics
from pydantic import BaseModel, ConfigDict

from posthog.schema import (
    ActorsPropertyTaxonomyQuery,
    ActorsQuery,
    CacheMissResponse,
    CalendarHeatmapQuery,
    ChartDisplayType,
    DashboardFilter,
    DateRange,
    EventsQuery,
    EventTaxonomyQuery,
    ExperimentExposureQuery,
    FilterLogicalOperator,
    FunnelCorrelationActorsQuery,
    FunnelCorrelationQuery,
    FunnelsActorsQuery,
    FunnelsQuery,
    GenericCachedQueryResponse,
    GroupsQuery,
    HogQLASTQuery,
    HogQLQuery,
    HogQLQueryModifiers,
    HogQLVariable,
    InsightActorsQuery,
    InsightActorsQueryOptions,
    LifecycleQuery,
    MarketingAnalyticsTableQuery,
    PathsQuery,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    QueryStatus,
    QueryStatusResponse,
    QueryTiming,
    RetentionQuery,
    SamplingRate,
    SessionAttributionExplorerQuery,
    SessionBatchEventsQuery,
    SessionsTimelineQuery,
    StickinessQuery,
    SuggestedQuestionsQuery,
    TeamTaxonomyQuery,
    TraceQuery,
    TracesQuery,
    TrendsQuery,
    VectorSearchQuery,
    WebGoalsQuery,
    WebOverviewQuery,
    WebStatsTableQuery,
    WebTrendsQuery,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database, create_hogql_database
from posthog.hogql.modifiers import create_default_modifiers_for_user
from posthog.hogql.printer import print_ast
from posthog.hogql.query import create_default_modifiers_for_team
from posthog.hogql.timings import HogQLTimings

from posthog import settings
from posthog.caching.utils import ThresholdMode, cache_target_age, is_stale, last_refresh_from_cached_result
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute_async import QueryNotFoundError, enqueue_process_query_task, get_query_status
from posthog.clickhouse.client.limit import (
    get_api_team_rate_limiter,
    get_app_dashboard_queries_rate_limiter,
    get_app_org_rate_limiter,
    get_org_app_concurrency_limit,
)
from posthog.clickhouse.query_tagging import get_query_tag_value, tag_queries
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_cache import count_query_cache_hit
from posthog.hogql_queries.query_cache_base import QueryCacheManagerBase
from posthog.hogql_queries.query_cache_factory import get_query_cache_manager
from posthog.hogql_queries.query_metadata import extract_query_metadata
from posthog.hogql_queries.utils.event_usage import log_event_usage_from_query_metadata
from posthog.models import Team, User
from posthog.models.team import WeekStartDay
from posthog.rbac.user_access_control import UserAccessControlError
from posthog.schema_helpers import to_dict
from posthog.utils import generate_cache_key, get_from_dict_or_attr, to_json

logger = structlog.get_logger(__name__)


EXTENDED_CACHE_AGE = timedelta(days=1)


class ExecutionMode(StrEnum):
    CALCULATE_BLOCKING_ALWAYS = "force_blocking"
    """Always recalculate."""
    CALCULATE_ASYNC_ALWAYS = "force_async"
    """Always kick off async calculation."""
    RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE = "blocking"
    """Use cache, unless the results are missing or stale."""
    RECENT_CACHE_CALCULATE_ASYNC_IF_STALE = "async"
    """Use cache, kick off async calculation when results are missing or stale."""
    RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS = "async_except_on_cache_miss"
    """Use cache, kick off async calculation when results are stale, but block on cache miss."""
    EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE = "lazy_async"
    """Use cache for longer, kick off async calculation when results are missing or stale."""
    CACHE_ONLY_NEVER_CALCULATE = "force_cache"
    """Do not initiate calculation."""


BLOCKING_EXECUTION_MODES: set[ExecutionMode] = {
    ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
    ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
    ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS,
}

_REFRESH_TO_EXECUTION_MODE: dict[str | bool, ExecutionMode] = {
    **ExecutionMode._value2member_map_,  # type: ignore
    True: ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
}


def execution_mode_from_refresh(refresh_requested: bool | str | None) -> ExecutionMode:
    if refresh_requested:
        if execution_mode := _REFRESH_TO_EXECUTION_MODE.get(refresh_requested):
            return execution_mode
    return ExecutionMode.CACHE_ONLY_NEVER_CALCULATE


_SHARED_MODE_WHITELIST = {
    # Cache only is default refresh mode - remap to async so shared insights stay fresh
    ExecutionMode.CACHE_ONLY_NEVER_CALCULATE: ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE,
    # Legacy refresh=true - but on shared insights, we don't give the ability to refresh at will
    # TODO: Adjust once shared insights can poll for async query_status
    ExecutionMode.CALCULATE_BLOCKING_ALWAYS: ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
    # Allow regular async
    ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE: ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE,
    # - All others fall back to extended cache -
}


def shared_insights_execution_mode(execution_mode: ExecutionMode) -> ExecutionMode:
    return _SHARED_MODE_WHITELIST.get(execution_mode, ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE)


RunnableQueryNode = Union[
    TrendsQuery,
    FunnelsQuery,
    RetentionQuery,
    PathsQuery,
    StickinessQuery,
    LifecycleQuery,
    ActorsQuery,
    EventsQuery,
    SessionBatchEventsQuery,
    HogQLQuery,
    InsightActorsQuery,
    FunnelsActorsQuery,
    FunnelCorrelationQuery,
    FunnelCorrelationActorsQuery,
    InsightActorsQueryOptions,
    SessionsTimelineQuery,
    WebOverviewQuery,
    WebStatsTableQuery,
    WebGoalsQuery,
    WebTrendsQuery,
    SessionAttributionExplorerQuery,
    MarketingAnalyticsTableQuery,
    ActorsPropertyTaxonomyQuery,
]


def get_query_runner(
    query: dict[str, Any] | RunnableQueryNode | BaseModel,
    team: Team,
    timings: Optional[HogQLTimings] = None,
    limit_context: Optional[LimitContext] = None,
    modifiers: Optional[HogQLQueryModifiers] = None,
) -> "QueryRunner":
    try:
        kind = get_from_dict_or_attr(query, "kind")
    except AttributeError:
        raise ValueError(f"Can't get a runner for an unknown query type: {query}")

    if kind == "TrendsQuery":
        # Check if this should use calendar heatmap runner instead
        query_obj = cast(TrendsQuery | dict[str, Any], query)
        trends_filter = get_from_dict_or_attr(query_obj, "trendsFilter") or {}
        display_type = get_from_dict_or_attr(trends_filter, "display") if trends_filter else None

        if display_type == ChartDisplayType.CALENDAR_HEATMAP:
            from .insights.trends.calendar_heatmap_trends_query_runner import CalendarHeatmapTrendsQueryRunner

            return CalendarHeatmapTrendsQueryRunner(
                query=query_obj,
                team=team,
                timings=timings,
                limit_context=limit_context,
                modifiers=modifiers,
            )

        from .insights.trends.trends_query_runner import TrendsQueryRunner

        return TrendsQueryRunner(
            query=query_obj,
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "FunnelsQuery":
        from .insights.funnels.funnels_query_runner import FunnelsQueryRunner

        return FunnelsQueryRunner(
            query=cast(FunnelsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "RetentionQuery":
        from .insights.retention_query_runner import RetentionQueryRunner

        return RetentionQueryRunner(
            query=cast(RetentionQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "PathsQuery":
        from .insights.paths_query_runner import PathsQueryRunner

        return PathsQueryRunner(
            query=cast(PathsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )

    if kind == "CalendarHeatmapQuery":
        from .insights.trends.calendar_heatmap_query_runner import CalendarHeatmapQueryRunner

        return CalendarHeatmapQueryRunner(
            query=cast(CalendarHeatmapQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "StickinessQuery":
        from .insights.stickiness_query_runner import StickinessQueryRunner

        return StickinessQueryRunner(
            query=cast(StickinessQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "LifecycleQuery":
        from .insights.lifecycle_query_runner import LifecycleQueryRunner

        return LifecycleQueryRunner(
            query=cast(LifecycleQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "EventsQuery":
        from .events_query_runner import EventsQueryRunner

        return EventsQueryRunner(
            query=cast(EventsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "SessionBatchEventsQuery":
        from .ai.session_batch_events_query_runner import SessionBatchEventsQueryRunner

        return SessionBatchEventsQueryRunner(
            query=cast(SessionBatchEventsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "ActorsQuery":
        from .actors_query_runner import ActorsQueryRunner

        return ActorsQueryRunner(
            query=cast(ActorsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )

    if kind == "GroupsQuery":
        from .groups.groups_query_runner import GroupsQueryRunner

        return GroupsQueryRunner(
            query=cast(GroupsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind in ("InsightActorsQuery", "FunnelsActorsQuery", "FunnelCorrelationActorsQuery", "StickinessActorsQuery"):
        from .insights.insight_actors_query_runner import InsightActorsQueryRunner

        return InsightActorsQueryRunner(
            query=cast(InsightActorsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "InsightActorsQueryOptions":
        from .insights.insight_actors_query_options_runner import InsightActorsQueryOptionsRunner

        return InsightActorsQueryOptionsRunner(
            query=cast(InsightActorsQueryOptions | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "FunnelCorrelationQuery":
        from .insights.funnels.funnel_correlation_query_runner import FunnelCorrelationQueryRunner

        return FunnelCorrelationQueryRunner(
            query=cast(FunnelCorrelationQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "HogQLQuery" or kind == "HogQLASTQuery":
        from .hogql_query_runner import HogQLQueryRunner

        return HogQLQueryRunner(
            query=cast(HogQLQuery | HogQLASTQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "SessionsTimelineQuery":
        from .sessions_timeline_query_runner import SessionsTimelineQueryRunner

        return SessionsTimelineQueryRunner(
            query=cast(SessionsTimelineQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )
    if kind == "WebOverviewQuery":
        from .web_analytics.web_overview import WebOverviewQueryRunner

        return WebOverviewQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "WebStatsTableQuery":
        from .web_analytics.stats_table import WebStatsTableQueryRunner

        return WebStatsTableQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "WebGoalsQuery":
        from .web_analytics.web_goals import WebGoalsQueryRunner

        return WebGoalsQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "WebTrendsQuery":
        from .web_analytics.web_trends_query_runner import WebTrendsQueryRunner

        return WebTrendsQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "WebExternalClicksTableQuery":
        from .web_analytics.external_clicks import WebExternalClicksTableQueryRunner

        return WebExternalClicksTableQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "WebVitalsPathBreakdownQuery":
        from .web_analytics.web_vitals_path_breakdown import WebVitalsPathBreakdownQueryRunner

        return WebVitalsPathBreakdownQueryRunner(
            query=query,
            team=team,
        )

    if kind == "WebPageURLSearchQuery":
        from .web_analytics.page_url_search_query_runner import PageUrlSearchQueryRunner

        return PageUrlSearchQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "SessionAttributionExplorerQuery":
        from .web_analytics.session_attribution_explorer_query_runner import SessionAttributionExplorerQueryRunner

        return SessionAttributionExplorerQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "RevenueAnalyticsGrossRevenueQuery":
        from products.revenue_analytics.backend.hogql_queries.revenue_analytics_gross_revenue_query_runner import (
            RevenueAnalyticsGrossRevenueQueryRunner,
        )

        return RevenueAnalyticsGrossRevenueQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "RevenueAnalyticsMetricsQuery":
        from products.revenue_analytics.backend.hogql_queries.revenue_analytics_metrics_query_runner import (
            RevenueAnalyticsMetricsQueryRunner,
        )

        return RevenueAnalyticsMetricsQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "RevenueAnalyticsMRRQuery":
        from products.revenue_analytics.backend.hogql_queries.revenue_analytics_mrr_query_runner import (
            RevenueAnalyticsMRRQueryRunner,
        )

        return RevenueAnalyticsMRRQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "RevenueAnalyticsOverviewQuery":
        from products.revenue_analytics.backend.hogql_queries.revenue_analytics_overview_query_runner import (
            RevenueAnalyticsOverviewQueryRunner,
        )

        return RevenueAnalyticsOverviewQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "RevenueAnalyticsTopCustomersQuery":
        from products.revenue_analytics.backend.hogql_queries.revenue_analytics_top_customers_query_runner import (
            RevenueAnalyticsTopCustomersQueryRunner,
        )

        return RevenueAnalyticsTopCustomersQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "RevenueExampleEventsQuery":
        from products.revenue_analytics.backend.hogql_queries.revenue_example_events_query_runner import (
            RevenueExampleEventsQueryRunner,
        )

        return RevenueExampleEventsQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "RevenueExampleDataWarehouseTablesQuery":
        from products.revenue_analytics.backend.hogql_queries.revenue_example_data_warehouse_tables_query_runner import (
            RevenueExampleDataWarehouseTablesQueryRunner,
        )

        return RevenueExampleDataWarehouseTablesQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "ErrorTrackingQuery":
        from .error_tracking_query_runner import ErrorTrackingQueryRunner

        return ErrorTrackingQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "ErrorTrackingIssueCorrelationQuery":
        from .error_tracking_issue_correlation_query_runner import ErrorTrackingIssueCorrelationQueryRunner

        return ErrorTrackingIssueCorrelationQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "ExperimentFunnelsQuery":
        from .experiments.experiment_funnels_query_runner import ExperimentFunnelsQueryRunner

        return ExperimentFunnelsQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "ExperimentTrendsQuery":
        from .experiments.experiment_trends_query_runner import ExperimentTrendsQueryRunner

        return ExperimentTrendsQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "ExperimentQuery":
        from .experiments.experiment_query_runner import ExperimentQueryRunner

        return ExperimentQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    if kind == "ExperimentExposureQuery":
        from posthog.hogql_queries.experiments.experiment_exposures_query_runner import ExperimentExposuresQueryRunner

        return ExperimentExposuresQueryRunner(
            query=cast(ExperimentExposureQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )

    if kind == "SuggestedQuestionsQuery":
        from posthog.hogql_queries.ai.suggested_questions_query_runner import SuggestedQuestionsQueryRunner

        return SuggestedQuestionsQueryRunner(
            query=cast(SuggestedQuestionsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "TeamTaxonomyQuery":
        from .ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner

        return TeamTaxonomyQueryRunner(
            query=cast(TeamTaxonomyQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "EventTaxonomyQuery":
        from .ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner

        return EventTaxonomyQueryRunner(
            query=cast(EventTaxonomyQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "ActorsPropertyTaxonomyQuery":
        from .ai.actors_property_taxonomy_query_runner import ActorsPropertyTaxonomyQueryRunner

        return ActorsPropertyTaxonomyQueryRunner(
            query=cast(ActorsPropertyTaxonomyQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "TracesQuery":
        from .legacy_compatibility.feature_flag import llm_analytics_traces_query_v2

        if llm_analytics_traces_query_v2(team):
            from .ai.traces_query_runner_v2 import TracesQueryRunnerV2

            return TracesQueryRunnerV2(
                query=cast(TracesQuery | dict[str, Any], query),
                team=team,
                timings=timings,
                limit_context=limit_context,
                modifiers=modifiers,
            )
        else:
            from .ai.traces_query_runner import TracesQueryRunner

            return TracesQueryRunner(
                query=cast(TracesQuery | dict[str, Any], query),
                team=team,
                timings=timings,
                limit_context=limit_context,
                modifiers=modifiers,
            )
    if kind == "TraceQuery":
        from .ai.trace_query_runner import TraceQueryRunner

        return TraceQueryRunner(
            query=cast(TraceQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "VectorSearchQuery":
        from .ai.vector_search_query_runner import VectorSearchQueryRunner

        return VectorSearchQueryRunner(
            query=cast(VectorSearchQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )

    if kind == "MarketingAnalyticsTableQuery":
        from products.marketing_analytics.backend.hogql_queries.marketing_analytics_table_query_runner import (
            MarketingAnalyticsTableQueryRunner,
        )

        return MarketingAnalyticsTableQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
        )

    raise ValueError(f"Can't get a runner for an unknown query kind: {kind}")


def get_query_runner_or_none(
    query: dict[str, Any] | RunnableQueryNode | BaseModel,
    team: Team,
    timings: Optional[HogQLTimings] = None,
    limit_context: Optional[LimitContext] = None,
    modifiers: Optional[HogQLQueryModifiers] = None,
) -> Optional["QueryRunner"]:
    try:
        return get_query_runner(
            query=query, team=team, timings=timings, limit_context=limit_context, modifiers=modifiers
        )
    except ValueError as e:
        if "Can't get a runner for an unknown" in str(e):
            return None
        raise


Q = TypeVar("Q", bound=RunnableQueryNode)
# R (for Response) should have a structure similar to QueryResponse
# Due to the way schema.py is generated, we don't have a good inheritance story here
R = TypeVar("R", bound=BaseModel)
# CR (for CachedResponse) must be R extended with CachedQueryResponseMixin
# Unfortunately inheritance is also not a thing here, because we lose this info in the schema.ts->.json->.py journey
CR = TypeVar("CR", bound=GenericCachedQueryResponse)


class QueryRunner(ABC, Generic[Q, R, CR]):
    query: Q
    response: R
    cached_response: CR
    query_id: Optional[str]

    team: Team
    timings: HogQLTimings
    modifiers: HogQLQueryModifiers
    limit_context: LimitContext
    # query service means programmatic access and /query endpoint
    is_query_service: bool = False
    workload: Workload

    def __init__(
        self,
        query: Q | BaseModel | dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
        query_id: Optional[str] = None,
        workload: Workload = Workload.DEFAULT,
        extract_modifiers=lambda query: (query.modifiers if hasattr(query, "modifiers") else None),
    ):
        self.team = team
        self.timings = timings or HogQLTimings()
        self.limit_context = limit_context or LimitContext.QUERY
        self.query_id = query_id
        self.workload = workload

        if not self.is_query_node(query):
            if isinstance(self.query_type, UnionType):
                for query_type in get_args(self.query_type):  # type: ignore
                    try:
                        query = query_type.model_validate(query)
                        break
                    except ValueError:
                        continue
                if not self.is_query_node(query):
                    raise ValueError(f"Query is not of type {self.query_type}")
            else:
                query = self.query_type.model_validate(query)
                assert isinstance(query, self.query_type)

        _modifiers = modifiers or extract_modifiers(query)
        self.modifiers = create_default_modifiers_for_team(team, _modifiers)
        self.query = query
        self.__post_init__()

    def __post_init__(self):
        """Called after init, can by overriden by subclasses. Should be idempotent. Also called after dashboard overrides are set."""
        pass

    @property
    def query_type(self) -> type[Q]:
        return self.__annotations__["query"]  # Enforcing the type annotation of `query` at runtime

    @property
    def cached_response_type(self) -> type[CR]:
        return self.__annotations__["cached_response"]

    def is_query_node(self, data) -> TypeGuard[Q]:
        return isinstance(data, self.query_type)

    def is_cached_response(self, data) -> TypeGuard[dict]:
        return hasattr(data, "is_cached") or (  # Duck typing for backwards compatibility with `CachedQueryResponse`
            isinstance(data, dict) and "is_cached" in data
        )

    @property
    def _limit_context_aliased_for_cache(self) -> LimitContext:
        # For caching purposes, QUERY_ASYNC is equivalent to QUERY (max query duration should be the only difference)
        if not self.limit_context or self.limit_context == LimitContext.QUERY_ASYNC:
            return LimitContext.QUERY
        return self.limit_context

    def calculate(self) -> R:
        return self._calculate()

    @abstractmethod
    def _calculate(self) -> R:
        raise NotImplementedError()

    def enqueue_async_calculation(
        self,
        *,
        cache_manager: QueryCacheManagerBase,
        refresh_requested: bool = False,
        user: Optional[User] = None,
    ) -> QueryStatus:
        posthoganalytics.capture(
            distinct_id=user.distinct_id if user else str(self.team.uuid),
            event="query async recalculation initiated",
            properties={
                "query_type": getattr(self.query, "kind", "Other"),
                "cache_key": cache_manager.cache_key,
                "insight_id": cache_manager.insight_id,
                "dashboard_id": cache_manager.dashboard_id,
                "refresh_requested": refresh_requested,
                "user_id": user.id if user else None,
            },
            groups=(groups(self.team.organization, self.team)),
        )

        return enqueue_process_query_task(
            team=self.team,
            user_id=user.id if user else None,
            insight_id=cache_manager.insight_id,
            dashboard_id=cache_manager.dashboard_id,
            query_json=self.query.model_dump(),
            query_id=self.query_id or cache_manager.cache_key,  # Use cache key as query ID to avoid duplicates
            cache_key=cache_manager.cache_key,
            refresh_requested=refresh_requested,
            is_query_service=self.is_query_service,
        )

    def get_async_query_status(self, *, cache_key: str) -> Optional[QueryStatus]:
        try:
            query_status = get_query_status(team_id=self.team.pk, query_id=self.query_id or cache_key)
            if query_status.complete:
                return None
            return query_status

        except QueryNotFoundError:
            return None

    def handle_cache_and_async_logic(
        self, execution_mode: ExecutionMode, cache_manager: QueryCacheManagerBase, user: Optional[User] = None
    ) -> Optional[CR | CacheMissResponse]:
        CachedResponse: type[CR] = self.cached_response_type
        cached_response: CR | CacheMissResponse
        cached_response_candidate = cache_manager.get_cache_data()

        if self.is_cached_response(cached_response_candidate):
            cached_response_candidate["is_cached"] = True
            # When rolling out schema changes, cached responses may not match the new schema.
            # Trigger recomputation in this case.
            try:
                cached_response = CachedResponse(**cached_response_candidate)
            except Exception as e:
                capture_exception(Exception(f"Error parsing cached response: {e}"))
                cached_response = CacheMissResponse(cache_key=cache_manager.cache_key)
        elif cached_response_candidate is None:
            cached_response = CacheMissResponse(cache_key=cache_manager.cache_key)
        else:
            # Whatever's in cache is malformed, so let's treat is as non-existent
            cached_response = CacheMissResponse(cache_key=cache_manager.cache_key)
            capture_exception(
                ValueError(f"Cached response is of unexpected type {type(cached_response)}, ignoring it"),
                {"cache_key": cache_manager.cache_key},
            )

        if self.is_cached_response(cached_response_candidate):
            assert isinstance(cached_response, CachedResponse)

            if not self._is_stale(last_refresh=last_refresh_from_cached_result(cached_response)):
                count_query_cache_hit(self.team.pk, hit="hit", trigger=cached_response.calculation_trigger or "")
                # We have a valid result that's fresh enough, let's return it
                cached_response.query_status = self.get_async_query_status(cache_key=cache_manager.cache_key)
                return cached_response

            count_query_cache_hit(self.team.pk, hit="stale", trigger=cached_response.calculation_trigger or "")
            # We have a stale result. If we aren't allowed to calculate, let's still return it
            # – otherwise let's proceed to calculation
            if execution_mode == ExecutionMode.CACHE_ONLY_NEVER_CALCULATE:
                cached_response.query_status = self.get_async_query_status(cache_key=cache_manager.cache_key)
                return cached_response
            elif execution_mode in (
                ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE,
                ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS,
            ):
                # We're allowed to calculate, but we'll do it asynchronously and attach the query status
                cached_response.query_status = self.enqueue_async_calculation(
                    cache_manager=cache_manager, user=user, refresh_requested=True
                )
                return cached_response
            elif execution_mode == ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE:
                # We're allowed to calculate if the lazy check fails, but we'll do it asynchronously
                assert isinstance(cached_response, CachedResponse)
                if self._is_stale(last_refresh=last_refresh_from_cached_result(cached_response), lazy=True):
                    cached_response.query_status = self.enqueue_async_calculation(
                        cache_manager=cache_manager, user=user
                    )
                cached_response.query_status = self.get_async_query_status(cache_key=cache_manager.cache_key)
                return cached_response
        else:
            count_query_cache_hit(self.team.pk, hit="miss", trigger="")
            # We have no cached result. If we aren't allowed to calculate, let's return the cache miss
            # – otherwise let's proceed to calculation
            if execution_mode == ExecutionMode.CACHE_ONLY_NEVER_CALCULATE:
                cached_response.query_status = self.get_async_query_status(cache_key=cache_manager.cache_key)
                return cached_response
            elif execution_mode in (
                ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE,
                ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE,
            ):
                # We're allowed to calculate, but we'll do it asynchronously
                cached_response.query_status = self.enqueue_async_calculation(cache_manager=cache_manager, user=user)
                return cached_response

        # Nothing useful out of cache, nor async query status
        return None

    def run(
        self,
        execution_mode: ExecutionMode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
        user: Optional[User] = None,
        query_id: Optional[str] = None,
        insight_id: Optional[int] = None,
        dashboard_id: Optional[int] = None,
    ) -> CR | CacheMissResponse | QueryStatusResponse:
        start_time = perf_counter()
        cache_key = self.get_cache_key()

        with posthoganalytics.new_context():
            posthoganalytics.tag("cache_key", cache_key)
            posthoganalytics.tag("query_type", getattr(self.query, "kind", "Other"))

            if insight_id:
                posthoganalytics.tag("insight_id", str(insight_id))
            if dashboard_id:
                posthoganalytics.tag("dashboard_id", str(dashboard_id))
            if tags := getattr(self.query, "tags", None):
                if tags.productKey:
                    posthoganalytics.tag("product_key", tags.productKey)
                if tags.scene:
                    posthoganalytics.tag("scene", tags.scene)

            # Abort early if the user doesn't have access to the query runner
            # We'll proceed as usual if there's no user connected to this request
            # We're capturing the error for analytics purposes, but we reraise the same one
            if user is not None:
                try:
                    self.validate_query_runner_access(user)
                except UserAccessControlError as error:
                    posthoganalytics.capture(
                        distinct_id=user.distinct_id,
                        event="query access control error",
                        properties={
                            "query_runner": self.__class__.__name__,
                            "query_id": self.query_id,
                            "insight_id": insight_id,
                            "dashboard_id": dashboard_id,
                            "execution_mode": execution_mode.value,
                            "query_type": getattr(self.query, "kind", "Other"),
                            "resource": error.resource,
                            "required_level": error.required_level,
                            "resource_id": error.resource_id,
                            "cache_key": cache_key,
                        },
                    )

                    raise

            trigger: str | None = get_query_tag_value("trigger")

            self.query_id = query_id or self.query_id
            CachedResponse: type[CR] = self.cached_response_type
            cache_manager = get_query_cache_manager(
                team=self.team,
                cache_key=cache_key,
                insight_id=insight_id,
                dashboard_id=dashboard_id,
            )

            if execution_mode == ExecutionMode.CALCULATE_ASYNC_ALWAYS:
                # We should always kick off async calculation and disregard the cache
                return QueryStatusResponse(
                    query_status=self.enqueue_async_calculation(
                        refresh_requested=True, cache_manager=cache_manager, user=user
                    )
                )
            elif execution_mode != ExecutionMode.CALCULATE_BLOCKING_ALWAYS:
                # Let's look in the cache first
                results = self.handle_cache_and_async_logic(
                    execution_mode=execution_mode, cache_manager=cache_manager, user=user
                )
                if results:
                    cache_tracking_props = {}
                    if isinstance(results, CachedResponse):
                        if (not trigger or not trigger.startswith("warming")) and results.query_metadata:
                            log_event_usage_from_query_metadata(
                                results.query_metadata,
                                team_id=self.team.id,
                                user_id=user.id if user else None,
                            )

                        last_refresh = last_refresh_from_cached_result(results)
                        cache_tracking_props = {
                            "is_cache_stale": self._is_stale(last_refresh=last_refresh),
                            "calculation_trigger": results.calculation_trigger,
                            "cache_age_seconds": round((datetime.now(UTC) - last_refresh).total_seconds(), 2)
                            if last_refresh
                            else None,
                            "last_refresh": last_refresh.isoformat() if last_refresh else None,
                        }

                    posthoganalytics.capture(
                        distinct_id=user.distinct_id if user else str(self.team.uuid),
                        event="query executed",
                        properties={
                            "insight_id": insight_id,
                            "dashboard_id": dashboard_id,
                            "execution_mode": execution_mode.value,
                            "query_type": getattr(self.query, "kind", "Other"),
                            "cache_key": cache_key,
                            "cache_hit": True if isinstance(results, CachedResponse) else False,
                            "response_time_ms": round((perf_counter() - start_time) * 1000, 2),
                            **cache_tracking_props,
                        },
                        groups=(groups(self.team.organization, self.team)),
                    )

                    return results

            last_refresh = datetime.now(UTC)
            target_age = self.cache_target_age(last_refresh=last_refresh)

            # Avoid affecting cache key
            # Add user based modifiers here, primarily for user specific feature flagging
            if user:
                self.modifiers = create_default_modifiers_for_user(user, self.team, self.modifiers)
                self.modifiers.useMaterializedViews = True

            concurrency_limit = self.get_api_queries_concurrency_limit()
            with get_api_team_rate_limiter().run(
                is_api=self.is_query_service,
                team_id=self.team.pk,
                task_id=self.query_id,
                limit=concurrency_limit,
            ):
                if self.is_query_service:
                    tag_queries(chargeable=1)

                with get_app_org_rate_limiter().run(
                    org_id=self.team.organization_id,
                    task_id=self.query_id,
                    team_id=self.team.id,
                    is_api=get_query_tag_value("access_method") == "personal_api_key",
                    limit=get_org_app_concurrency_limit(self.team.organization_id),
                ):
                    with get_app_dashboard_queries_rate_limiter().run(
                        org_id=self.team.organization_id,
                        dashboard_id=dashboard_id,
                        task_id=self.query_id,
                        team_id=self.team.id,
                        is_api=get_query_tag_value("access_method") == "personal_api_key",
                    ):
                        query_start_time = perf_counter()
                        query_result = self.calculate()
                        query_duration_ms = round((perf_counter() - query_start_time) * 1000, 2)

                        fresh_response_dict = {
                            **query_result.model_dump(),
                            "is_cached": False,
                            "last_refresh": last_refresh,
                            "next_allowed_client_refresh": last_refresh + self._refresh_frequency(),
                            "cache_key": cache_key,
                            "timezone": self.team.timezone,
                            "cache_target_age": target_age,
                        }

            try:
                query_metadata = extract_query_metadata(query=self.query, team=self.team).model_dump()
                fresh_response_dict["query_metadata"] = query_metadata

                # Don't log usage for warming queries
                if not trigger or not trigger.startswith("warming"):
                    log_event_usage_from_query_metadata(
                        query_metadata,
                        team_id=self.team.id,
                        user_id=user.id if user else None,
                    )
            except Exception as e:
                # fail silently if we can't extract query metadata
                capture_exception(
                    e, {"query": self.query, "team_id": self.team.pk, "context": "query_metadata_extract"}
                )

            if trigger:
                fresh_response_dict["calculation_trigger"] = trigger

            # Don't cache debug queries with errors and export queries
            errors: Optional[list] = fresh_response_dict.get("error", None)
            has_error = errors is not None and len(errors) > 0
            if not has_error and self.limit_context != LimitContext.EXPORT:
                cache_manager.set_cache_data(
                    response=fresh_response_dict,
                    # This would be a possible place to decide to not ever keep this cache warm
                    # Example: Not for super quickly calculated insights
                    # Set target_age to None in that case
                    target_age=target_age,
                )

            posthoganalytics.capture(
                distinct_id=user.distinct_id if user else str(self.team.uuid),
                event="query executed",
                properties={
                    "insight_id": insight_id,
                    "dashboard_id": dashboard_id,
                    "cache_hit": False,
                    "cache_key": cache_key,
                    "calculation_trigger": trigger,
                    "execution_mode": execution_mode.value,
                    "query_type": getattr(self.query, "kind", "Other"),
                    "response_time_ms": round((perf_counter() - start_time) * 1000, 2),
                    "query_duration_ms": query_duration_ms,
                    "has_error": has_error,
                },
                groups=(groups(self.team.organization, self.team)),
            )

            return CachedResponse(**fresh_response_dict)

    def get_api_queries_concurrency_limit(self):
        """
        :return: None - no feature, 0 - rate limited, 1,3,<other> for actual concurrency limit
        """

        if not settings.EE_AVAILABLE or not settings.API_QUERIES_ENABLED:
            return None

        from posthog.constants import AvailableFeature

        from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, list_limited_team_attributes

        if self.team.api_token in list_limited_team_attributes(
            QuotaResource.API_QUERIES, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        ):
            return 0

        feature = self.team.organization.get_available_feature(AvailableFeature.API_QUERIES_CONCURRENCY)
        return feature.get("limit") if feature else None

    @abstractmethod
    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        raise NotImplementedError()

    def to_actors_query(self, *args, **kwargs) -> ast.SelectQuery | ast.SelectSetQuery:
        # TODO: add support for selecting and filtering by breakdowns
        raise NotImplementedError()

    def to_hogql(self, **kwargs) -> str:
        with self.timings.measure("to_hogql"):
            return print_ast(
                self.to_query(),
                HogQLContext(
                    team_id=self.team.pk,
                    enable_select_queries=True,
                    timings=self.timings,
                    modifiers=self.modifiers,
                ),
                "hogql",
                **kwargs,
            )

    def get_cache_payload(self) -> dict:
        # remove the tags key, these are used in the query log comment but shouldn't break caching
        query = to_dict(self.query)
        query.pop("tags", None)

        return {
            "query_runner": self.__class__.__name__,
            "query": query,
            "team_id": self.team.pk,
            "hogql_modifiers": to_dict(self.modifiers),
            "products_modifiers": {
                "revenue_analytics": self.team.revenue_analytics_config.to_cache_key_dict(),
                "marketing_analytics": self.team.marketing_analytics_config.to_cache_key_dict(),
            },
            "limit_context": self._limit_context_aliased_for_cache,
            "timezone": self.team.timezone,
            "week_start_day": self.team.week_start_day or WeekStartDay.SUNDAY,
            "version": 2,
        }

    def get_cache_key(self) -> str:
        return generate_cache_key(f"query_{bytes.decode(to_json(self.get_cache_payload()))}")

    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        if last_refresh is None:
            return None
        query_date_range = getattr(self, "query_date_range", None)
        interval = query_date_range.interval_name if query_date_range else "minute"
        mode = ThresholdMode.LAZY if lazy else ThresholdMode.DEFAULT
        return cache_target_age(interval, last_refresh=last_refresh, mode=mode)

    def validate_query_runner_access(self, user: User) -> bool:
        """
        Child query runners can override this to check if the user has access to the query runner
        by using the user_access_control.check_access_level_for_resource method

        It should return `True` if the user has access to the query runner, or raise a `UserAccessControlError` if they don't.

        Example:
        ```
        from posthog.rbac.user_access_control import UserAccessControl

        def validate_query_runner_access(self, user: User) -> bool:
            user_access_control = UserAccessControl(user=user, team=self.team)
            if not user_access_control.check_access_level_for_resource("revenue_analytics", "viewer"):
                raise UserAccessControlError("revenue_analytics", "viewer")
        ```

        Example using `assert_access_level_for_resource`:
        ```
        from posthog.rbac.user_access_control import UserAccessControl

        def validate_query_runner_access(self, user: User) -> bool:
            user_access_control = UserAccessControl(user=user, team=self.team)
            return user_access_control.assert_access_level_for_resource("revenue_analytics", "viewer")
        ```

        Args:
            user: The user to check access for

        Returns:
            `True` if the user has access to the query runner

        Raises:
            `UserAccessControlError` if the user does not have access to the query runner
        """
        return True

    def _is_stale(self, last_refresh: Optional[datetime], lazy: bool = False) -> bool:
        query_date_range = getattr(self, "query_date_range", None)
        date_to = query_date_range.date_to() if query_date_range else None
        interval = query_date_range.interval_name if query_date_range else "minute"
        mode = ThresholdMode.LAZY if lazy else ThresholdMode.DEFAULT
        return is_stale(self.team, date_to=date_to, interval=interval, last_refresh=last_refresh, mode=mode)

    def _refresh_frequency(self) -> timedelta:
        return timedelta(minutes=1)

    def apply_variable_overrides(self, variable_overrides: list[HogQLVariable]):
        """Irreversibly update self.query with provided variable overrides."""
        if not hasattr(self.query, "variables") or not self.query.kind == "HogQLQuery" or len(variable_overrides) == 0:
            return

        assert isinstance(self.query, HogQLQuery)

        if not self.query.variables:
            return

        for variable in variable_overrides:
            if self.query.variables.get(variable.variableId):
                self.query.variables[variable.variableId] = variable

    def apply_dashboard_filters(self, dashboard_filter: DashboardFilter):
        """Irreversibly update self.query with provided dashboard filters."""
        if not hasattr(self.query, "properties") or not hasattr(self.query, "dateRange"):
            capture_exception(
                NotImplementedError(
                    f"{self.query.__class__.__name__} does not support dashboard filters out of the box"
                )
            )
            return

        # The default logic below applies to all insights and a lot of other queries
        # Notable exception: `HogQLQuery`, which has `properties` and `dateRange` within `HogQLFilters`
        if dashboard_filter.properties:
            if self.query.properties:
                try:
                    self.query.properties = PropertyGroupFilter(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            (
                                PropertyGroupFilterValue(type=FilterLogicalOperator.AND_, values=self.query.properties)
                                if isinstance(self.query.properties, list)
                                else PropertyGroupFilterValue(**self.query.properties.model_dump())
                            ),
                            PropertyGroupFilterValue(
                                type=FilterLogicalOperator.AND_, values=dashboard_filter.properties
                            ),
                        ],
                    )
                except:
                    # If pydantic is unhappy about the shape of data, let's ignore property filters and carry on
                    capture_exception()
                    logger.exception("Failed to apply dashboard property filters")
            else:
                self.query.properties = dashboard_filter.properties
        if dashboard_filter.date_from or dashboard_filter.date_to:
            if self.query.dateRange is None:
                self.query.dateRange = DateRange()
            self.query.dateRange.date_from = dashboard_filter.date_from
            self.query.dateRange.date_to = dashboard_filter.date_to

        if dashboard_filter.breakdown_filter:
            if hasattr(self.query, "breakdownFilter"):
                self.query.breakdownFilter = dashboard_filter.breakdown_filter
            else:
                capture_exception(
                    NotImplementedError(
                        f"{self.query.__class__.__name__} does not support breakdown filters out of the box"
                    )
                )
        self.__post_init__()


# Type constraint for analytics query responses
class AnalyticsQueryResponseProtocol(Protocol):
    timings: Optional[list[QueryTiming]]


AR = TypeVar("AR", bound=AnalyticsQueryResponseProtocol)


class AnalyticsQueryRunner(QueryRunner, Generic[AR]):
    """
    QueryRunner subclass that constrains the response type to AnalyticsQueryResponseBase.
    When subclassing this, give it a single generic argument of the Response type
    e.g. class TeamTaxonomyQueryRunner(TaxonomyCacheMixin, AnalyticsQueryRunner[TeamTaxonomyQueryResponse]):
    """

    def calculate(self) -> AR:
        response = self._calculate()
        if not self.modifiers.timings:
            response.timings = None
        return response


class QueryRunnerWithHogQLContext(AnalyticsQueryRunner[AR]):
    database: Database
    hogql_context: HogQLContext

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # We create a new context here because we need to access the database
        # below in the to_query method and creating a database is pretty heavy
        # so we'll reuse this database for the query once it eventually runs
        self.database = create_hogql_database(team=self.team)
        self.hogql_context = HogQLContext(team_id=self.team.pk, database=self.database)


### START OF BACKWARDS COMPATIBILITY CODE

# In May 2024 we've switched from a single shared `CachedQueryResponse` to a `Cached*QueryResponse` being defined
# for each runnable query kind, so we won't be creating new `CachedQueryResponse`s. Unfortunately, as of May 2024,
# we're pickling cached query responses instead of e.g. serializing to JSON, so we have to unpickle them later.
# Because of that, we need `CachedQueryResponse` to still be defined here till the end of May 2024 - otherwise
# we wouldn't be able to unpickle and therefore use cached results from before this change was merged.

DataT = TypeVar("DataT")


class QueryResponse(BaseModel, Generic[DataT]):
    model_config = ConfigDict(
        extra="forbid",
    )
    results: DataT
    timings: Optional[list[QueryTiming]] = None
    types: Optional[list[Union[tuple[str, str], str]]] = None
    columns: Optional[list[str]] = None
    error: Optional[str] = None
    hogql: Optional[str] = None
    hasMore: Optional[bool] = None
    limit: Optional[int] = None
    offset: Optional[int] = None
    samplingRate: Optional[SamplingRate] = None
    modifiers: Optional[HogQLQueryModifiers] = None


class CachedQueryResponse(QueryResponse):
    model_config = ConfigDict(
        extra="forbid",
    )
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    cache_key: str
    timezone: str


### END OF BACKWARDS COMPATIBILITY CODE
