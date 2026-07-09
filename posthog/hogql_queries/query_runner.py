from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from time import perf_counter
from types import UnionType
from typing import Any, Generic, Optional, Protocol, TypeGuard, TypeVar, Union, cast, get_args, get_origin

import structlog
import posthoganalytics
from prometheus_client import Counter, Histogram
from pydantic import BaseModel, ConfigDict

from posthog.schema import (
    AccountsQuery,
    ActorsPropertyTaxonomyQuery,
    ActorsQuery,
    BreakdownType,
    CacheMissResponse,
    CalendarHeatmapQuery,
    ChartDisplayType,
    DashboardAutoRefreshInterval,
    DashboardFilter,
    DateRange,
    EndpointsUsageOverviewQuery,
    EndpointsUsageTableQuery,
    EndpointsUsageTrendsQuery,
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
    HogQLQuery,
    HogQLQueryModifiers,
    HogQLVariable,
    InsightActorsQuery,
    InsightActorsQueryOptions,
    LifecycleQuery,
    MarketingAnalyticsAggregatedQuery,
    MarketingAnalyticsTableQuery,
    MCPHarnessBreakdownQuery,
    MCPToolDailyStatsQuery,
    MCPToolDescriptionsQuery,
    MCPToolFailuresQuery,
    MCPToolNeighborsQuery,
    MCPToolSampleIntentsQuery,
    MCPToolStatsQuery,
    MCPToolTopUsersQuery,
    NodeKind,
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
    SessionQuery,
    SessionsQuery,
    SessionsTimelineQuery,
    StickinessQuery,
    SuggestedQuestionsQuery,
    TeamTaxonomyQuery,
    TraceNeighborsQuery,
    TraceQuery,
    TracesQuery,
    TrendsQuery,
    UsageMetricsQuery,
    VectorSearchQuery,
    WebGoalsQuery,
    WebNotableChangesQuery,
    WebOverviewQuery,
    WebStatsTableQuery,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_user
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import create_default_modifiers_for_team
from posthog.hogql.timings import HogQLTimings
from posthog.hogql.warehouse_warnings import accumulator_scope

from posthog import settings
from posthog.caching.utils import ThresholdMode, cache_target_age, is_stale, last_refresh_from_cached_result
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute_async import QueryNotFoundError, enqueue_process_query_task, get_query_status
from posthog.clickhouse.client.limit import (
    get_api_team_rate_limiter,
    get_app_dashboard_queries_rate_limiter,
    get_app_org_rate_limiter,
    get_materialized_endpoints_rate_limiter,
    get_org_app_concurrency_limit,
)
from posthog.clickhouse.query_tagging import get_query_tag_value, is_api_key_access_method, tag_queries
from posthog.constants import AvailableFeature
from posthog.errors import QueryErrorCategory, classify_query_error, clickhouse_error_type
from posthog.event_usage import AnalyticsProps, groups, report_user_or_team_action
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.access_controlled_resources import queried_access_controlled_resources
from posthog.hogql_queries.insights.utils.breakdowns import has_multi_breakdown, has_single_breakdown
from posthog.hogql_queries.insights.utils.entities import has_data_warehouse_node
from posthog.hogql_queries.insights.utils.properties import has_any_property_filters
from posthog.hogql_queries.query_cache import count_query_cache_hit
from posthog.hogql_queries.query_cache_base import QueryCacheManagerBase
from posthog.hogql_queries.query_cache_factory import get_query_cache_manager
from posthog.hogql_queries.query_metadata import extract_query_metadata
from posthog.hogql_queries.utils.event_usage import log_event_usage_from_query_metadata
from posthog.hogql_queries.validation.validation import (
    QueryValidationContext,
    QueryValidationRule,
    run_validation_rules,
)
from posthog.models import Team, User
from posthog.models.team import WeekStartDay
from posthog.models.team.event_retention import events_retention_months_for_team
from posthog.rbac.user_access_control import WAREHOUSE_ACCESS_SCOPES, UserAccessControl, UserAccessControlError
from posthog.schema_helpers import to_dict
from posthog.scopes import APIScopeObject
from posthog.shared_link_user import SharedLinkUser
from posthog.slo.context import JsonValue, SloSpec, slo_operation
from posthog.slo.types import SloArea, SloOperation, SloOutcome
from posthog.synthetic_user import SyntheticUser
from posthog.utils import generate_cache_key, get_from_dict_or_attr, to_json

logger = structlog.get_logger(__name__)

QUERY_EXECUTION_TOTAL = Counter(
    "posthog_query_execution_total",
    "Query executions by category",
    labelnames=["query_type", "category", "error_type", "contains_user_hogql"],
)

QUERY_EXECUTION_DURATION = Histogram(
    "posthog_query_execution_duration_seconds",
    "Query execution duration in seconds",
    labelnames=["query_type"],
    buckets=[0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 7.5, 10.0, 15.0, 20.0, 30.0, 60.0, 120.0],
)

SURVEY_QUERY_EXECUTION_TOTAL = Counter(
    "posthog_survey_query_execution_total",
    "Query executions by category",
    labelnames=["query_type", "query_name", "category", "error_type"],
)

SURVEY_QUERY_EXECUTION_DURATION = Histogram(
    "posthog_survey_query_execution_duration_seconds",
    "Query execution duration in seconds",
    labelnames=["query_type", "query_name"],
    buckets=[0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 7.5, 10.0, 15.0, 20.0, 30.0, 60.0, 120.0],
)


def _contains_user_hogql_label() -> str:
    # Read the tag set by `tag_contains_user_hogql()` at HogQL parse sites; lets
    # observability split user-HogQL failures from query-builder failures on the
    # same metric. The tag is the canonical source — see `posthog.clickhouse.query_tagging`.
    return "true" if get_query_tag_value("contains_user_hogql") else "false"


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

_REFRESH_TO_EXECUTION_MODE: dict[str | bool, ExecutionMode] = {  # ty: ignore[invalid-assignment]
    **ExecutionMode._value2member_map_,  # type: ignore
    True: ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
}

UNKNOWN_QUERY_METRIC_LABEL = "unknown"
SURVEYS_PRODUCT_KEY = "surveys"


def get_survey_query_metric_labels(query: Any) -> dict[str, str] | None:
    tags = getattr(query, "tags", None)
    if getattr(tags, "productKey", None) != SURVEYS_PRODUCT_KEY:
        return None

    return {
        "query_type": getattr(query, "kind", "Other"),
        "query_name": getattr(tags, "name", None) or UNKNOWN_QUERY_METRIC_LABEL,
    }


def execution_mode_from_refresh(refresh_requested: bool | str | None) -> ExecutionMode:
    if refresh_requested:
        if execution_mode := _REFRESH_TO_EXECUTION_MODE.get(refresh_requested):
            return execution_mode
    return ExecutionMode.CACHE_ONLY_NEVER_CALCULATE


# Minimum age before a shared insight may honor `?refresh=force_blocking`.
# Sourced from the same generated schema as the frontend's auto-refresh interval so the
# two cannot drift. Best-effort throttle, not a hard rate limit.
SHARED_FORCE_BLOCKING_MIN_AGE = timedelta(seconds=DashboardAutoRefreshInterval().root)


_SHARED_MODE_WHITELIST = {
    ExecutionMode.CACHE_ONLY_NEVER_CALCULATE: ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE,
    # force_blocking is gated by `shared_insights_execution_mode`; downgrades to IF_STALE
    # when the throttle clock is younger than `SHARED_FORCE_BLOCKING_MIN_AGE`.
    ExecutionMode.CALCULATE_BLOCKING_ALWAYS: ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
    ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE: ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE,
    # Used by the shared-notebook inline query payload builder. Without this entry the
    # request silently falls through to EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE, which causes
    # the frontend to incorrectly render a "unsupported node" placeholder until the async calc finishes and a later reload picks up the warm cache.
    ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE: ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
}


def _is_force_blocking_eligible_for_shared(last_refresh: datetime | None) -> bool:
    if last_refresh is None:
        return False
    return datetime.now(UTC) - last_refresh >= SHARED_FORCE_BLOCKING_MIN_AGE


def _classify_error_for_slo(exc: Exception) -> tuple[QueryErrorCategory, SloOutcome]:
    """Classify a query exception for SLO emission.

    Returns the QueryErrorCategory plus the SloOutcome that should be reported:

    - USER_ERROR / RATE_LIMITED / CANCELLED → SUCCESS. They reflect user input,
      abuse, or normal interaction (cancel-on-navigate-away), not platform
      reliability. The completed event still fires with the error_category tag
      so dashboards can slice by it.
    - QUERY_PERFORMANCE_ERROR and unclassified exceptions → FAILURE. Timeouts
      and OOM dominate that category at scale; the user-input limits inside it
      (EstimatedQueryExecutionTimeTooLong, QuerySizeExceeded) are a minority
      worth living with for now.

    UserAccessControlError is folded into USER_ERROR locally since
    classify_query_error doesn't recognise it but a 403 is the user's input,
    not a service failure.
    """
    if isinstance(exc, UserAccessControlError):
        return QueryErrorCategory.USER_ERROR, SloOutcome.SUCCESS
    category = classify_query_error(exc)
    if category in (QueryErrorCategory.USER_ERROR, QueryErrorCategory.RATE_LIMITED, QueryErrorCategory.CANCELLED):
        return category, SloOutcome.SUCCESS
    return category, SloOutcome.FAILURE


def shared_insights_execution_mode(
    execution_mode: ExecutionMode,
    *,
    last_refresh: datetime | None = None,
) -> ExecutionMode:
    if execution_mode == ExecutionMode.CALCULATE_BLOCKING_ALWAYS and not _is_force_blocking_eligible_for_shared(
        last_refresh
    ):
        logger.info(
            "shared_force_blocking_throttled",
            last_refresh=last_refresh.isoformat() if last_refresh else None,
            min_age_seconds=int(SHARED_FORCE_BLOCKING_MIN_AGE.total_seconds()),
        )
        return ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
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
    SessionQuery,
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
    WebNotableChangesQuery,
    SessionAttributionExplorerQuery,
    MarketingAnalyticsTableQuery,
    MarketingAnalyticsAggregatedQuery,
    ActorsPropertyTaxonomyQuery,
    UsageMetricsQuery,
    AccountsQuery,
    EndpointsUsageOverviewQuery,
    EndpointsUsageTableQuery,
    EndpointsUsageTrendsQuery,
    MCPHarnessBreakdownQuery,
    MCPToolTopUsersQuery,
    MCPToolFailuresQuery,
    MCPToolStatsQuery,
    MCPToolDailyStatsQuery,
    MCPToolDescriptionsQuery,
    MCPToolSampleIntentsQuery,
    MCPToolNeighborsQuery,
]


def get_query_runner(
    query: dict[str, Any] | RunnableQueryNode | BaseModel,
    team: Team,
    timings: Optional[HogQLTimings] = None,
    limit_context: Optional[LimitContext] = None,
    modifiers: Optional[HogQLQueryModifiers] = None,
    user: Optional[User] = None,
) -> "QueryRunner":
    try:
        kind = get_from_dict_or_attr(query, "kind")
    except AttributeError:
        raise ValueError(f"Can't get a runner for an unknown query type: {query}")

    if kind in ("DataTableNode", "DataVisualizationNode", "InsightVizNode"):
        source = get_from_dict_or_attr(query, "source")
        return get_query_runner(
            query=source,
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )

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
                user=user,
            )

        if display_type == ChartDisplayType.BOX_PLOT:
            from .insights.trends.boxplot_trends_query_runner import BoxPlotTrendsQueryRunner

            return BoxPlotTrendsQueryRunner(
                query=query_obj,
                team=team,
                timings=timings,
                limit_context=limit_context,
                modifiers=modifiers,
                user=user,
            )

        if display_type == ChartDisplayType.SLOPE_GRAPH:
            from .insights.trends.slope_graph_trends_query_runner import SlopeGraphTrendsQueryRunner

            return SlopeGraphTrendsQueryRunner(
                query=query_obj,
                team=team,
                timings=timings,
                limit_context=limit_context,
                modifiers=modifiers,
                user=user,
            )

        from .insights.trends.trends_query_runner import TrendsQueryRunner

        return TrendsQueryRunner(
            query=query_obj,
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "FunnelsQuery":
        from .insights.funnels.funnels_query_runner import FunnelsQueryRunner

        return FunnelsQueryRunner(
            query=cast(FunnelsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "RetentionQuery":
        from .insights.retention.retention_query_runner import RetentionQueryRunner

        return RetentionQueryRunner(
            query=cast(RetentionQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "PathsQuery":
        from products.product_analytics.backend.hogql_queries.paths.paths_query_runner import PathsQueryRunner

        return PathsQueryRunner(
            query=cast(PathsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )

    if kind == "CalendarHeatmapQuery":
        from .insights.trends.calendar_heatmap_query_runner import CalendarHeatmapQueryRunner

        return CalendarHeatmapQueryRunner(
            query=cast(CalendarHeatmapQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "StickinessQuery":
        from products.product_analytics.backend.hogql_queries.stickiness.stickiness_query_runner import (
            StickinessQueryRunner,
        )

        return StickinessQueryRunner(
            query=cast(StickinessQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "LifecycleQuery":
        from .insights.lifecycle.lifecycle_query_runner import LifecycleQueryRunner

        return LifecycleQueryRunner(
            query=cast(LifecycleQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "EventsQuery":
        from .events_query_runner import EventsQueryRunner

        return EventsQueryRunner(
            query=cast(EventsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "SessionsQuery":
        from .sessions_query_runner import SessionsQueryRunner

        return SessionsQueryRunner(
            query=cast(SessionsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "SessionBatchEventsQuery":
        from .ai.session_batch_events_query_runner import SessionBatchEventsQueryRunner

        return SessionBatchEventsQueryRunner(
            query=cast(SessionBatchEventsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "SessionQuery":
        from .ai.session_query_runner import SessionQueryRunner

        return SessionQueryRunner(
            query=cast(SessionQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "ActorsQuery":
        from .actors_query_runner import ActorsQueryRunner

        return ActorsQueryRunner(
            query=cast(ActorsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )

    if kind == "GroupsQuery":
        from .groups.groups_query_runner import GroupsQueryRunner

        return GroupsQueryRunner(
            query=cast(GroupsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind in (
        "InsightActorsQuery",
        "FunnelsActorsQuery",
        "FunnelCorrelationActorsQuery",
        "ExperimentActorsQuery",
        "StickinessActorsQuery",
    ):
        from .insights.insight_actors_query_runner import InsightActorsQueryRunner

        return InsightActorsQueryRunner(
            query=cast(InsightActorsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "InsightActorsQueryOptions":
        from .insights.insight_actors_query_options_runner import InsightActorsQueryOptionsRunner

        return InsightActorsQueryOptionsRunner(
            query=cast(InsightActorsQueryOptions | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "FunnelCorrelationQuery":
        from .insights.funnels.funnel_correlation_query_runner import FunnelCorrelationQueryRunner

        return FunnelCorrelationQueryRunner(
            query=cast(FunnelCorrelationQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "HogQLQuery":
        from .hogql_query_runner import HogQLQueryRunner

        return HogQLQueryRunner(
            query=cast(HogQLQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "SessionsTimelineQuery":
        from .sessions_timeline_query_runner import SessionsTimelineQueryRunner

        return SessionsTimelineQueryRunner(
            query=cast(SessionsTimelineQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )
    if kind == "WebOverviewQuery":
        from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner

        return WebOverviewQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "WebStatsTableQuery":
        from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner

        return WebStatsTableQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "WebGoalsQuery":
        from products.web_analytics.backend.hogql_queries.web_goals import WebGoalsQueryRunner

        return WebGoalsQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "WebNotableChangesQuery":
        from products.web_analytics.backend.hogql_queries.notable_changes import WebNotableChangesQueryRunner

        return WebNotableChangesQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "WebExternalClicksTableQuery":
        from products.web_analytics.backend.hogql_queries.external_clicks import WebExternalClicksTableQueryRunner

        return WebExternalClicksTableQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "WebVitalsPathBreakdownQuery":
        from products.web_analytics.backend.hogql_queries.web_vitals_path_breakdown import (
            WebVitalsPathBreakdownQueryRunner,
        )

        return WebVitalsPathBreakdownQueryRunner(
            query=query,
            team=team,
        )

    if kind == "WebPageURLSearchQuery":
        from products.web_analytics.backend.hogql_queries.page_url_search_query_runner import PageUrlSearchQueryRunner

        return PageUrlSearchQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "SessionAttributionExplorerQuery":
        from products.web_analytics.backend.hogql_queries.session_attribution_explorer_query_runner import (
            SessionAttributionExplorerQueryRunner,
        )

        return SessionAttributionExplorerQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
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
            user=user,
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
            user=user,
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
            user=user,
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
            user=user,
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
            user=user,
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
            user=user,
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
            user=user,
        )

    if kind == "ErrorTrackingQuery":
        from products.error_tracking.backend.facade.queries import ErrorTrackingQueryRunner

        return ErrorTrackingQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "DocumentSimilarityQuery":
        from .document_embeddings_query_runner import DocumentEmbeddingsQueryRunner

        return DocumentEmbeddingsQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "ErrorTrackingIssueCorrelationQuery":
        from products.error_tracking.backend.facade.queries import ErrorTrackingIssueCorrelationQueryRunner

        return ErrorTrackingIssueCorrelationQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "ErrorTrackingSimilarIssuesQuery":
        from products.error_tracking.backend.facade.queries import ErrorTrackingSimilarIssuesQueryRunner

        return ErrorTrackingSimilarIssuesQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "ErrorTrackingBreakdownsQuery":
        from products.error_tracking.backend.facade.queries import ErrorTrackingBreakdownsQueryRunner

        return ErrorTrackingBreakdownsQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "ExperimentFunnelsQuery":
        from products.experiments.backend.hogql_queries.experiment_funnels_query_runner import (
            ExperimentFunnelsQueryRunner,
        )

        return ExperimentFunnelsQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "ExperimentTrendsQuery":
        from products.experiments.backend.hogql_queries.experiment_trends_query_runner import (
            ExperimentTrendsQueryRunner,
        )

        return ExperimentTrendsQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "ExperimentQuery":
        from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner

        return ExperimentQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "ExperimentExposureQuery":
        from products.experiments.backend.hogql_queries.experiment_exposures_query_runner import (
            ExperimentExposuresQueryRunner,
        )

        return ExperimentExposuresQueryRunner(
            query=cast(ExperimentExposureQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )

    if kind == "SuggestedQuestionsQuery":
        from posthog.hogql_queries.ai.suggested_questions_query_runner import SuggestedQuestionsQueryRunner

        return SuggestedQuestionsQueryRunner(
            query=cast(SuggestedQuestionsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "TeamTaxonomyQuery":
        from .ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner

        return TeamTaxonomyQueryRunner(
            query=cast(TeamTaxonomyQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "EventTaxonomyQuery":
        from .ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner

        return EventTaxonomyQueryRunner(
            query=cast(EventTaxonomyQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "ActorsPropertyTaxonomyQuery":
        from .ai.actors_property_taxonomy_query_runner import ActorsPropertyTaxonomyQueryRunner

        return ActorsPropertyTaxonomyQueryRunner(
            query=cast(ActorsPropertyTaxonomyQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "TracesQuery":
        from .ai.traces_query_runner import TracesQueryRunner

        return TracesQueryRunner(
            query=cast(TracesQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "MCPHarnessBreakdownQuery":
        from products.mcp_analytics.backend.facade.queries import MCPHarnessBreakdownQueryRunner

        return MCPHarnessBreakdownQueryRunner(
            query=cast(MCPHarnessBreakdownQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "MCPToolTopUsersQuery":
        from products.mcp_analytics.backend.facade.queries import MCPToolTopUsersQueryRunner

        return MCPToolTopUsersQueryRunner(
            query=cast(MCPToolTopUsersQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "MCPToolFailuresQuery":
        from products.mcp_analytics.backend.facade.queries import MCPToolFailuresQueryRunner

        return MCPToolFailuresQueryRunner(
            query=cast(MCPToolFailuresQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "MCPToolStatsQuery":
        from products.mcp_analytics.backend.facade.queries import MCPToolStatsQueryRunner

        return MCPToolStatsQueryRunner(
            query=cast(MCPToolStatsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "MCPToolDailyStatsQuery":
        from products.mcp_analytics.backend.facade.queries import MCPToolDailyStatsQueryRunner

        return MCPToolDailyStatsQueryRunner(
            query=cast(MCPToolDailyStatsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "MCPToolDescriptionsQuery":
        from products.mcp_analytics.backend.facade.queries import MCPToolDescriptionsQueryRunner

        return MCPToolDescriptionsQueryRunner(
            query=cast(MCPToolDescriptionsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "MCPToolSampleIntentsQuery":
        from products.mcp_analytics.backend.facade.queries import MCPToolSampleIntentsQueryRunner

        return MCPToolSampleIntentsQueryRunner(
            query=cast(MCPToolSampleIntentsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "MCPToolNeighborsQuery":
        from products.mcp_analytics.backend.facade.queries import MCPToolNeighborsQueryRunner

        return MCPToolNeighborsQueryRunner(
            query=cast(MCPToolNeighborsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "TraceQuery":
        from .ai.trace_query_runner import TraceQueryRunner

        return TraceQueryRunner(
            query=cast(TraceQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "TraceNeighborsQuery":
        from .ai.trace_neighbors_query_runner import TraceNeighborsQueryRunner

        return TraceNeighborsQueryRunner(
            query=cast(TraceNeighborsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    if kind == "VectorSearchQuery":
        from .ai.vector_search_query_runner import VectorSearchQueryRunner

        return VectorSearchQueryRunner(
            query=cast(VectorSearchQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )

    if kind == NodeKind.MARKETING_ANALYTICS_TABLE_QUERY:
        from products.marketing_analytics.backend.hogql_queries.marketing_analytics_table_query_runner import (
            MarketingAnalyticsTableQueryRunner,
        )

        return MarketingAnalyticsTableQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == NodeKind.MARKETING_ANALYTICS_AGGREGATED_QUERY:
        from products.marketing_analytics.backend.hogql_queries.marketing_analytics_aggregated_query_runner import (
            MarketingAnalyticsAggregatedQueryRunner,
        )

        return MarketingAnalyticsAggregatedQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == NodeKind.NON_INTEGRATED_CONVERSIONS_TABLE_QUERY:
        from products.marketing_analytics.backend.hogql_queries.non_integrated_conversions_table_query_runner import (
            NonIntegratedConversionsTableQueryRunner,
        )

        return NonIntegratedConversionsTableQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "UsageMetricsQuery":
        from products.customer_analytics.backend.facade.queries import UsageMetricsQueryRunner

        return UsageMetricsQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "AccountsQuery":
        from products.customer_analytics.backend.facade.queries import AccountsQueryRunner

        return AccountsQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "EndpointsUsageOverviewQuery":
        from .endpoints.endpoints_usage_overview import EndpointsUsageOverviewQueryRunner

        return EndpointsUsageOverviewQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "EndpointsUsageTableQuery":
        from .endpoints.endpoints_usage_table import EndpointsUsageTableQueryRunner

        return EndpointsUsageTableQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "EndpointsUsageTrendsQuery":
        from .endpoints.endpoints_usage_trends import EndpointsUsageTrendsQueryRunner

        return EndpointsUsageTrendsQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "RecordingsQuery":
        from posthog.session_recordings.queries.recordings_query_runner import RecordingsQueryRunner

        return RecordingsQueryRunner(
            query=query,
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )

    # Registered here for server-side CSV export only (ExportedAsset + Celery).
    # Direct queries are blocked by LogsQueryRunner.validate_query_runner_access.
    if kind == "LogsQuery":
        from products.logs.backend.facade.queries import LogsQueryRunner

        return LogsQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "TraceSpansQuery":
        from posthog.schema import TraceSpansQuery

        from products.tracing.backend.logic import TraceSpansQueryRunner

        return TraceSpansQueryRunner(
            query=cast(TraceSpansQuery, query),
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    if kind == "PropertyValuesQuery":
        from posthog.hogql_queries.property_values_query_runner import PropertyValuesQueryRunner

        return PropertyValuesQueryRunner(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            user=user,
        )

    raise ValueError(f"Can't get a runner for an unknown query kind: {kind}")


def get_query_runner_or_none(
    query: dict[str, Any] | RunnableQueryNode | BaseModel,
    team: Team,
    timings: Optional[HogQLTimings] = None,
    limit_context: Optional[LimitContext] = None,
    modifiers: Optional[HogQLQueryModifiers] = None,
    user: Optional[User] = None,
    user_access_control: Optional[UserAccessControl] = None,
) -> Optional["QueryRunner"]:
    try:
        runner = get_query_runner(
            query=query,
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
            user=user,
        )
    except ValueError as e:
        if "Can't get a runner for an unknown" in str(e):
            return None
        raise
    # Reuse the caller's preloaded snapshot (e.g. one per request shared across a dashboard's
    # insight runners) so the cache fingerprint doesn't bulk-load access control once per runner.
    if user_access_control is not None and isinstance(runner, AnalyticsQueryRunner):
        runner._user_access_control = user_access_control
    return runner


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
    user: Optional[User]
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
        extract_modifiers=lambda query: query.modifiers if hasattr(query, "modifiers") else None,
        user: Optional[User] = None,
    ):
        self.team = team
        self.user = user
        self.timings = timings or HogQLTimings()
        self.limit_context = limit_context or LimitContext.QUERY
        self.query_id = query_id
        self.workload = workload

        if not self.is_query_node(query):
            if isinstance(self.query_type, UnionType):
                for query_type in get_args(self.query_type):
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

    def _on_user_changed(self) -> None:
        """Hook called by run() when self.user is updated after construction.

        Subclasses can override to rebuild any user-dependent state (e.g. a
        cached HogQLContext / Database that was created with a stale user)."""
        pass

    @property
    def query_type(self) -> Any:
        return self.__annotations__["query"]  # Enforcing the type annotation of `query` at runtime

    @property
    def cached_response_type(self) -> type[CR]:
        return self.__annotations__["cached_response"]

    def is_query_node(self, data) -> TypeGuard[Q]:
        query_type: Any = self.query_type
        query_type = getattr(query_type, "__value__", query_type)
        # Handle both UnionType and typing._UnionGenericAlias
        if isinstance(query_type, UnionType) or (type(query_type).__name__ == "_UnionGenericAlias"):
            return any(isinstance(data, t) for t in get_args(query_type))
        if not isinstance(query_type, type):
            raise TypeError(f"query_type must be a type, got {type(query_type)}: {query_type}")
        return isinstance(data, query_type)

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
        self.validate()
        return self._calculate()

    def validate(self) -> None:
        run_validation_rules(self.validators(), self.validation_context)

    @abstractmethod
    def _calculate(self) -> R:
        raise NotImplementedError()

    def enqueue_async_calculation(
        self,
        *,
        cache_manager: QueryCacheManagerBase,
        refresh_requested: bool = False,
        user: Optional[User] = None,
        analytics_props: Optional[AnalyticsProps] = None,
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
            is_posthog_ai=self.limit_context == LimitContext.POSTHOG_AI,
            analytics_props=analytics_props,
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
        self,
        execution_mode: ExecutionMode,
        cache_manager: QueryCacheManagerBase,
        user: Optional[User] = None,
        analytics_props: Optional[AnalyticsProps] = None,
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

        if isinstance(cached_response, CachedResponse):
            # Apply current query's custom_name values to cached response
            # (custom_name is excluded from cache key, so cached values may be stale)
            cached_response, custom_names_modified = self.apply_series_custom_names(cached_response)

            if custom_names_modified:
                # Update cache with patched response so subsequent requests get the updated names
                cache_manager.set_cache_data(
                    response=cached_response.model_dump(),
                    target_age=cached_response.cache_target_age,
                )

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
                    cache_manager=cache_manager, user=user, refresh_requested=True, analytics_props=analytics_props
                )
                return cached_response
            elif execution_mode == ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE:
                # We're allowed to calculate if the lazy check fails, but we'll do it asynchronously
                assert isinstance(cached_response, CachedResponse)
                if self._is_stale(last_refresh=last_refresh_from_cached_result(cached_response), lazy=True):
                    cached_response.query_status = self.enqueue_async_calculation(
                        cache_manager=cache_manager, user=user, analytics_props=analytics_props
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
                cached_response.query_status = self.enqueue_async_calculation(
                    cache_manager=cache_manager, user=user, analytics_props=analytics_props
                )
                return cached_response

        # Nothing useful out of cache, nor async query status
        return None

    def _call_with_rate_limits(self, *, dashboard_id: Optional[int]) -> tuple[R, float]:
        """Execute calculate() with all rate limiters applied.

        Returns:
            Tuple of (query_result, query_duration_ms)
        """
        concurrency_limit = self.get_api_queries_concurrency_limit()
        is_materialized_endpoint = get_query_tag_value("workload") == Workload.ENDPOINTS
        is_api_key_access = is_api_key_access_method(get_query_tag_value("access_method"))

        if self.is_query_service:
            tag_queries(chargeable=1)

        with (
            get_materialized_endpoints_rate_limiter().run(
                team_id=self.team.pk,
                task_id=self.query_id,
                is_materialized_endpoint=is_materialized_endpoint,
            ),
            get_api_team_rate_limiter().run(
                is_api=self.is_query_service and not is_materialized_endpoint,
                team_id=self.team.pk,
                task_id=self.query_id,
                limit=concurrency_limit,
            ),
            get_app_org_rate_limiter().run(
                org_id=self.team.organization_id,
                task_id=self.query_id,
                team_id=self.team.id,
                is_api=is_api_key_access,
                limit=get_org_app_concurrency_limit(self.team.organization_id),
            ),
            get_app_dashboard_queries_rate_limiter().run(
                org_id=self.team.organization_id,
                dashboard_id=dashboard_id,
                task_id=self.query_id,
                team_id=self.team.id,
                is_api=is_api_key_access,
            ),
        ):
            query_start_time = perf_counter()
            query_result = self.calculate()
            query_duration_ms = round((perf_counter() - query_start_time) * 1000, 2)
            return query_result, query_duration_ms

    def run(
        self,
        execution_mode: ExecutionMode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
        user: Optional[User] = None,
        query_id: Optional[str] = None,
        insight_id: Optional[int] = None,
        dashboard_id: Optional[int] = None,
        cache_age_seconds: Optional[int] = None,
        analytics_props: Optional[AnalyticsProps] = None,
    ) -> CR | CacheMissResponse | QueryStatusResponse:
        # Set user for access control during query execution. Some subclasses
        # (e.g. QueryRunnerWithHogQLContext) construct user-dependent state in
        # __init__; let them refresh it now that we know the real user. Only on an
        # actual change - re-running for the same user would needlessly rebuild that
        # state and drop a preloaded access-control snapshot.
        if user is not None and user is not self.user:
            self.user = user
            self._on_user_changed()
        start_time = perf_counter()
        cache_key = self.get_cache_key()
        # Resolve per-call state before observability so SLO + analytics agree on the values.
        self.query_id = query_id or self.query_id
        self._cache_age_override = cache_age_seconds

        # capture_exceptions=False: we capture explicitly at the except boundary below, so benign
        # user-input query errors (USER_ERROR / cancelled / rate-limited) are returned to the user
        # as 4xx without also polluting error tracking with server-side exception noise.
        with posthoganalytics.new_context(capture_exceptions=False):
            query_type = getattr(self.query, "kind", "Other")
            distinct_id = str(user.distinct_id) if user else str(self.team.uuid)

            posthoganalytics.tag("cache_key", cache_key)
            posthoganalytics.tag("query_type", query_type)

            if insight_id:
                posthoganalytics.tag("insight_id", str(insight_id))
            if dashboard_id:
                posthoganalytics.tag("dashboard_id", str(dashboard_id))

            product_key: str | None = None
            if tags := getattr(self.query, "tags", None):
                if tags.name:
                    posthoganalytics.tag("query_name", tags.name)
                    tag_queries(name=tags.name)
                if tags.productKey:
                    product_key = tags.productKey
                    posthoganalytics.tag("product_key", product_key)
                    tag_queries(product=tags.productKey)
                if tags.scene:
                    posthoganalytics.tag("scene", tags.scene)
                    tag_queries(scene=tags.scene)

            tag_queries(execution_mode=execution_mode.value)
            tag_queries(cache_key=cache_key)

            slo_properties: dict[str, JsonValue] = {
                "query_type": query_type,
                "execution_mode": execution_mode.value,
            }
            if insight_id is not None:
                slo_properties["insight_id"] = insight_id
            if dashboard_id is not None:
                slo_properties["dashboard_id"] = dashboard_id
            if product_key is not None:
                slo_properties["product_key"] = product_key

            with slo_operation(
                spec=SloSpec(
                    distinct_id=distinct_id,
                    area=SloArea.ANALYTIC_PLATFORM,
                    operation=SloOperation.QUERY_SERVICE,
                    team_id=self.team.id,
                    resource_id=self.query_id,
                    sample_rate=settings.QUERY_SERVICE_SLO_SAMPLE_RATE,
                ),
                properties=slo_properties,
            ) as slo:
                try:
                    # Abort early if the user doesn't have access to the query runner.
                    # We'll proceed as usual if there's no user connected to this request, or for an
                    # anonymous principal (SharedLinkUser) - the share link is its authorization.
                    # We're capturing the error for analytics purposes, but we reraise the same one
                    if user is not None and not user.is_anonymous:
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
                                    "query_type": query_type,
                                    "resource": error.resource,
                                    "required_level": error.required_level,
                                    "resource_id": error.resource_id,
                                    "cache_key": cache_key,
                                },
                            )

                            raise

                    trigger: str | None = get_query_tag_value("trigger")

                    CachedResponse: type[CR] = self.cached_response_type
                    cache_manager = get_query_cache_manager(
                        team=self.team,
                        cache_key=cache_key,
                        insight_id=insight_id,
                        dashboard_id=dashboard_id,
                    )

                    if execution_mode == ExecutionMode.CALCULATE_ASYNC_ALWAYS:
                        # We should always kick off async calculation and disregard the cache.
                        # cache_hit is left unset on this path because the cache wasn't consulted.
                        slo.tag(execution_path="async_dispatched")
                        return QueryStatusResponse(
                            query_status=self.enqueue_async_calculation(
                                refresh_requested=True,
                                cache_manager=cache_manager,
                                user=user,
                                analytics_props=analytics_props,
                            )
                        )
                    elif execution_mode != ExecutionMode.CALCULATE_BLOCKING_ALWAYS:
                        # Let's look in the cache first
                        results = self.handle_cache_and_async_logic(
                            execution_mode=execution_mode,
                            cache_manager=cache_manager,
                            user=user,
                            analytics_props=analytics_props,
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
                                slo.tag(
                                    execution_path="cache_hit",
                                    cache_hit=True,
                                    **cache_tracking_props,
                                )
                            else:
                                slo.tag(execution_path="cache_miss", cache_hit=False)

                            query_executed_props = {
                                "insight_id": insight_id,
                                "dashboard_id": dashboard_id,
                                "execution_mode": execution_mode.value,
                                "query_type": query_type,
                                "cache_key": cache_key,
                                "cache_hit": isinstance(results, CachedResponse),
                                "response_time_ms": round((perf_counter() - start_time) * 1000, 2),
                                **cache_tracking_props,
                            }
                            report_user_or_team_action(
                                "query executed",
                                query_executed_props,
                                user=user,
                                team=self.team,
                                organization=self.team.organization,
                                analytics_props=analytics_props,
                            )

                            return results

                    # cache_hit is left unset on this path: either the caller passed
                    # CALCULATE_BLOCKING_ALWAYS (cache skipped) or the cache returned nothing.
                    slo.tag(execution_path="blocking", calculation_trigger=trigger)
                    return self._execute_and_cache_blocking(
                        cache_key=cache_key,
                        cache_manager=cache_manager,
                        execution_mode=execution_mode,
                        insight_id=insight_id,
                        dashboard_id=dashboard_id,
                        trigger=trigger,
                        user=user,
                        start_time=start_time,
                        analytics_props=analytics_props,
                    )
                except Exception as exc:
                    # Don't pass execution_path here: whichever branch tag was set before the raise
                    # (cache_hit / cache_miss / blocking / async_dispatched) stays intact so
                    # dashboards can attribute errors to the path they happened in. Errors that fire
                    # before any branch tag is set leave execution_path unset, which is honest.
                    category, outcome = _classify_error_for_slo(exc)
                    if outcome == SloOutcome.SUCCESS:
                        slo.succeed(error_category=category.value)
                    else:
                        slo.fail(error_category=category.value)
                        # Capture only what classifies as a FAILURE outcome. User-input query errors
                        # (USER_ERROR / cancelled / rate-limited) classify as SUCCESS above and are
                        # deliberately not captured — they're returned to the user as 4xx. Note this
                        # gate is the SLO outcome, not a strict platform-vs-user split:
                        # QUERY_PERFORMANCE_ERROR is FAILURE (so captured) even though a minority of
                        # those are user-input limits — see _classify_error_for_slo.
                        capture_exception(exc)
                    raise

    def _execute_and_cache_blocking(
        self,
        *,
        cache_key: str,
        cache_manager: QueryCacheManagerBase,
        execution_mode: ExecutionMode,
        insight_id: Optional[int],
        dashboard_id: Optional[int],
        trigger: Optional[str],
        user: Optional[User],
        start_time: float,
        analytics_props: Optional["AnalyticsProps"] = None,
    ) -> CR:
        CachedResponse: type[CR] = self.cached_response_type

        last_refresh = datetime.now(UTC)
        target_age = self.cache_target_age(last_refresh=last_refresh)

        # Avoid affecting cache key
        # Add user based modifiers here, primarily for user specific feature flagging
        if user:
            self.modifiers = create_default_modifiers_for_user(user, self.team, self.modifiers)
            self.modifiers.useMaterializedViews = True

        # Capture data warehouse sync warnings from every HogQL execution that contributes to this
        # response. Nested calls (one runner invoking another) see the parent's accumulator via
        # ContextVar and contribute to it; the outermost scope is the one that attaches and resets.
        with accumulator_scope() as warnings_accumulator:
            query_type = getattr(self.query, "kind", "Other")
            survey_query_metric_labels = get_survey_query_metric_labels(self.query)
            query_start = perf_counter()
            try:
                query_result, query_duration_ms = self._call_with_rate_limits(dashboard_id=dashboard_id)
                QUERY_EXECUTION_TOTAL.labels(
                    query_type=query_type,
                    category="success",
                    error_type="none",
                    contains_user_hogql=_contains_user_hogql_label(),
                ).inc()
                if survey_query_metric_labels:
                    SURVEY_QUERY_EXECUTION_TOTAL.labels(
                        **survey_query_metric_labels, category="success", error_type="none"
                    ).inc()
            except Exception as e:
                QUERY_EXECUTION_TOTAL.labels(
                    query_type=query_type,
                    category=classify_query_error(e),
                    error_type=clickhouse_error_type(e),
                    contains_user_hogql=_contains_user_hogql_label(),
                ).inc()
                if survey_query_metric_labels:
                    SURVEY_QUERY_EXECUTION_TOTAL.labels(
                        **survey_query_metric_labels,
                        category=classify_query_error(e),
                        error_type=clickhouse_error_type(e),
                    ).inc()
                raise
            finally:
                query_duration_seconds = perf_counter() - query_start
                QUERY_EXECUTION_DURATION.labels(query_type=query_type).observe(query_duration_seconds)
                if survey_query_metric_labels:
                    SURVEY_QUERY_EXECUTION_DURATION.labels(**survey_query_metric_labels).observe(query_duration_seconds)

            fresh_response_dict: dict[str, Any] = {
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

            # Attach accumulated warehouse sync warnings before caching, so cache hits replay them.
            # Guard against response classes that don't carry the field: every analytics response
            # inherits `warnings` from AnalyticsQueryResponseBase, and several standalone classes
            # add it explicitly — but a future response class that omits it would otherwise crash
            # pydantic validation on the extra key (and poison the cache, which set_cache_data has
            # already written by the time CachedResponse(**dict) raises).
            if warnings_accumulator and "warnings" in CachedResponse.model_fields:
                fresh_response_dict["warnings"] = [w.model_dump() for w in warnings_accumulator.values()]

            # Don't cache debug queries with errors and export queries
            errors: Optional[list[Any]] = fresh_response_dict.get("error", None)
            has_error = errors is not None and len(errors) > 0
            if not has_error and self.limit_context != LimitContext.EXPORT:
                cache_manager.set_cache_data(
                    response=fresh_response_dict,
                    # This would be a possible place to decide to not ever keep this cache warm
                    # Example: Not for super quickly calculated insights
                    # Set target_age to None in that case
                    target_age=target_age,
                )

            query_executed_props = {
                "insight_id": insight_id,
                "dashboard_id": dashboard_id,
                "cache_hit": False,
                "cache_key": cache_key,
                "calculation_trigger": trigger,
                "execution_mode": execution_mode.value,
                "query_type": query_type,
                "response_time_ms": round((perf_counter() - start_time) * 1000, 2),
                "query_duration_ms": query_duration_ms,
                "has_error": has_error,
            }
            report_user_or_team_action(
                "query executed",
                query_executed_props,
                user=user,
                team=self.team,
                organization=self.team.organization,
                analytics_props=analytics_props,
            )

            return CachedResponse(**fresh_response_dict)

    def get_api_queries_concurrency_limit(self):
        """
        :return: None - no feature, 0 - rate limited, 1,3,<other> for actual concurrency limit
        """

        # TODO - remove once no longer needed, as per https://posthog.slack.com/archives/C075D3C5HST/p1766275591753869
        if self.team.pk and self.team.pk == 117239:
            return 20  # Matches org-level limit

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
            return prepare_and_print_ast(
                self.to_query(),
                HogQLContext(
                    team_id=self.team.pk,
                    enable_select_queries=True,
                    timings=self.timings,
                    modifiers=self.modifiers,
                ),
                "hogql",
                **kwargs,
            )[0]

    def get_cache_payload(self) -> dict:
        # remove the tags key, these are used in the query log comment but shouldn't break caching
        # note: to_dict already strips custom_name from series (see schema_helpers.py)
        query = to_dict(self.query)
        query.pop("tags", None)

        payload = {
            "query_runner": self.__class__.__name__,
            "query": query,
            "team_id": self.team.pk,
            "hogql_modifiers": to_dict(self.modifiers),
            "products_modifiers": {
                "revenue_analytics": self.team.revenue_analytics_config.to_cache_key_dict(),
                "marketing_analytics": self.team.marketing_analytics_config.to_cache_key_dict(),
                "customer_analytics": self.team.customer_analytics_config.to_cache_key_dict(),
            },
            "limit_context": self._limit_context_aliased_for_cache,
            "timezone": self.team.timezone,
            "week_start_day": self.team.week_start_day or WeekStartDay.SUNDAY,
            "version": 2,
        }

        # Include property-level access control restrictions in the cache key so that
        # users with different property restrictions get separate cache entries.
        restricted = self._get_property_access_restrictions()
        if restricted:
            payload["restricted_properties"] = restricted

        # Vary the cache key by the events-retention floor: a cache hit returns before the printer applies the floor,
        # so without this a result cached pre-enforcement (or at a longer period) would keep surfacing events past
        # retention. Only set when enforced, so non-cohort teams' keys are unchanged.
        retention_months = events_retention_months_for_team(self.team, self.team.pk)
        if retention_months is not None:
            payload["events_retention_floor_months"] = retention_months

        return payload

    def _get_property_access_restrictions(self) -> list[tuple[str, int]] | None:
        """Returns a sorted list of restricted (property_name, type) pairs for the current user, or None if no restrictions.

        The underlying ``get_restricted_properties_for_team`` memoizes per request,
        so rendering a dashboard with N insights issues one PropertyAccessControl
        lookup per (team, user) pair instead of N.
        """
        from products.access_control.backend.property_access_control import get_restricted_properties_for_team

        restricted = get_restricted_properties_for_team(user=self.user, team=self.team)
        if not restricted:
            return None
        return sorted(restricted)

    def get_cache_key(self) -> str:
        return generate_cache_key(self.team.pk, f"query_{bytes.decode(to_json(self.get_cache_payload()))}")

    def apply_series_custom_names(self, cached_response: CR) -> tuple[CR, bool]:
        """
        Apply custom_name values from the current query's series to a cached response.

        Since custom_name is excluded from cache keys (it's presentation metadata),
        cached responses may have stale custom_name values. This method patches
        the response with the current query's custom_name values.

        Returns:
            Tuple of (patched_response, was_modified) - was_modified is True if any
            custom_name values were actually changed.
        """
        if isinstance(self.query, TrendsQuery | StickinessQuery | LifecycleQuery):
            return self._apply_trends_custom_names(cached_response)
        elif isinstance(self.query, FunnelsQuery):
            return self._apply_funnels_custom_names(cached_response)
        return cached_response, False

    def _apply_trends_custom_names(self, cached_response: CR) -> tuple[CR, bool]:
        """Apply custom_name values to TrendsQuery results (nested under action)."""
        series = getattr(self.query, "series", None)
        if not series:
            return cached_response, False

        results = getattr(cached_response, "results", None)
        if not results or not isinstance(results, list):
            return cached_response, False

        custom_names_by_order: dict[int, str | None] = {}
        for i, s in enumerate(series):
            custom_name = getattr(s, "custom_name", None)
            custom_names_by_order[i] = custom_name

        was_modified = False
        for result in results:
            if not isinstance(result, dict):
                continue
            action = result.get("action")
            if not isinstance(action, dict):
                continue
            order = action.get("order")
            if order is not None and order in custom_names_by_order:
                new_name = custom_names_by_order[order]
                if action.get("custom_name") != new_name:
                    action["custom_name"] = new_name
                    was_modified = True

        return cached_response, was_modified

    def _apply_funnels_custom_names(self, cached_response: CR) -> tuple[CR, bool]:
        """
        Apply custom_name values to FunnelsQuery results (top-level of step dict).

        Funnel results have two structures:
        - Without breakdown: flat list of steps [step1, step2, ...]
        - With breakdown: list of lists [[step1, step2], [step1, step2], ...]
        """
        series = getattr(self.query, "series", None)
        if not series:
            return cached_response, False

        results = getattr(cached_response, "results", None)
        if not results or not isinstance(results, list):
            return cached_response, False

        custom_names_by_order: dict[int, str | None] = {}
        for i, s in enumerate(series):
            custom_name = getattr(s, "custom_name", None)
            custom_names_by_order[i] = custom_name

        was_modified = False

        if results and len(results) > 0 and isinstance(results[0], list):
            # Breakdown case: iterate through each breakdown group
            for breakdown_group in results:
                for step in breakdown_group:
                    if not isinstance(step, dict):
                        continue
                    order = step.get("order")
                    if order is not None and order in custom_names_by_order:
                        new_name = custom_names_by_order[order]
                        if step.get("custom_name") != new_name:
                            step["custom_name"] = new_name
                            was_modified = True
        else:
            # Non-breakdown case: flat list of steps
            for step in results:
                if not isinstance(step, dict):
                    continue
                order = step.get("order")
                if order is not None and order in custom_names_by_order:
                    new_name = custom_names_by_order[order]
                    if step.get("custom_name") != new_name:
                        step["custom_name"] = new_name
                        was_modified = True

        return cached_response, was_modified

    def _get_cache_age_override(self, last_refresh: Optional[datetime]) -> Optional[datetime]:
        """
        Helper method for subclasses that override cache_target_age().
        Returns the custom cache target age if _cache_age_override is set, otherwise None.

        Subclasses can call this first in their cache_target_age() implementation:
        ```
        override = self._get_cache_age_override(last_refresh)
        if override is not None:
            return override
        # ... custom logic
        ```
        """
        if hasattr(self, "_cache_age_override") and self._cache_age_override is not None and last_refresh is not None:
            return last_refresh + timedelta(seconds=self._cache_age_override)
        return None

    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        if last_refresh is None:
            return None

        # Check for custom cache age override (e.g., from Endpoint)
        override_target_age = self._get_cache_age_override(last_refresh)
        if override_target_age is not None:
            return override_target_age

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

    @property
    def validation_context(self) -> QueryValidationContext[Q]:
        return QueryValidationContext(query=self.query, team=self.team, user=self.user, runner=self)

    def validators(self) -> Sequence[QueryValidationRule[Q]]:
        """Overridden by subclasses to add validation rules."""
        return ()

    def _is_stale(self, last_refresh: Optional[datetime], lazy: bool = False) -> bool:
        # If a custom cache age was provided (e.g., from Endpoint), use our override logic
        target_age = None
        if hasattr(self, "_cache_age_override") and self._cache_age_override is not None:
            target_age = self.cache_target_age(last_refresh, lazy=lazy)
            if not target_age:
                return False

        query_date_range = getattr(self, "query_date_range", None)
        date_to = query_date_range.date_to() if query_date_range else None
        interval = query_date_range.interval_name if query_date_range else "minute"
        mode = ThresholdMode.LAZY if lazy else ThresholdMode.DEFAULT
        return is_stale(
            self.team, date_to=date_to, interval=interval, last_refresh=last_refresh, mode=mode, target_age=target_age
        )

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

    def apply_pagination_cursor(self, cursor: str) -> None:
        """Apply an opaque cursor for paginating through results. Override in subclasses."""
        pass

    def apply_dashboard_filters(self, dashboard_filter: DashboardFilter):
        """Irreversibly update self.query with provided dashboard filters."""
        if not hasattr(self.query, "properties") or not hasattr(self.query, "dateRange"):
            capture_exception(
                NotImplementedError(
                    f"{self.query.__class__.__name__} does not support dashboard filters out of the box"
                )
            )
            return

        has_data_warehouse_series = (
            hasattr(self.query, "series")
            and isinstance(self.query.series, list)
            and has_data_warehouse_node(self.query.series)
        )

        dashboard_breakdown_filter = dashboard_filter.breakdown_filter

        should_ignore_dashboard_breakdown = not hasattr(self.query, "breakdownFilter") or (
            isinstance(self.query, TrendsQuery)
            and has_data_warehouse_series
            and (
                has_multi_breakdown(dashboard_breakdown_filter)
                or (
                    has_single_breakdown(dashboard_breakdown_filter)
                    and dashboard_breakdown_filter is not None
                    and dashboard_breakdown_filter.breakdown_type != BreakdownType.DATA_WAREHOUSE
                )
            )
        )

        if dashboard_filter.properties and not has_data_warehouse_series:
            if self.query.properties and has_any_property_filters(self.query.properties):
                # Check if query expects only a list (e.g. WebOverviewQuery) vs union with PropertyGroupFilter
                properties_field = self.query.__class__.model_fields.get("properties")
                expects_only_list = properties_field and get_origin(properties_field.annotation) is list

                if expects_only_list and isinstance(self.query.properties, list):
                    # Concatenate lists to avoid TypeError when query does: properties + other_list
                    self.query.properties = list(self.query.properties) + list(dashboard_filter.properties)
                else:
                    # Wrap in PropertyGroupFilter with AND
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
            else:
                self.query.properties = list(dashboard_filter.properties)
        if dashboard_filter.date_from or dashboard_filter.date_to:
            if self.query.dateRange is None:
                self.query.dateRange = DateRange()
            date_range = self.query.dateRange
            assert date_range is not None
            date_range.date_from = dashboard_filter.date_from
            date_range.date_to = dashboard_filter.date_to

            if dashboard_filter.explicitDate is not None:
                date_range.explicitDate = dashboard_filter.explicitDate

        if dashboard_filter.breakdown_filter and not should_ignore_dashboard_breakdown:
            if hasattr(self.query, "breakdownFilter"):  # redundant, but required for mypy
                self.query.breakdownFilter = dashboard_filter.breakdown_filter

        # Interval and test-account overrides apply only to query types that carry the field.
        # Types without it (retention, paths) are silently skipped rather than mutated.
        if dashboard_filter.interval is not None and hasattr(self.query, "interval"):
            self.query.interval = dashboard_filter.interval

        if dashboard_filter.filterTestAccounts is not None and hasattr(self.query, "filterTestAccounts"):
            self.query.filterTestAccounts = dashboard_filter.filterTestAccounts

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

    _user_access_control: Optional[UserAccessControl] = None

    def calculate(self) -> AR:
        response = super().calculate()
        if not self.modifiers.timings:
            response.timings = None
        return response

    def _on_user_changed(self) -> None:
        super()._on_user_changed()
        self._user_access_control = None

    @property
    def user_access_control(self) -> Optional[UserAccessControl]:
        """Access-control snapshot for the cache fingerprint. Built lazily - the fingerprint runs
        before any database exists, which a cache hit never reaches. None if the principal is not a
        real User (service tokens and shared-link viewers have no RBAC)."""
        user = self.user
        if not isinstance(user, User):
            return None
        if self._user_access_control is None:
            self._user_access_control = UserAccessControl(user=user, team=self.team)
        return self._user_access_control

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()

        # Don't include restricted resources/objects in cache_payload if the ACCESS_CONTROL is unavailable
        if isinstance(self.user, User) and not self.team.organization.is_feature_available(
            AvailableFeature.ACCESS_CONTROL
        ):
            return payload

        # Partition only by the access-controlled tables this query reads that the user is restricted
        # from - so queries on events, persons and other non-access-controlled tables share one cache
        # entry (incl. userless cache warming).
        queried_resources = queried_access_controlled_resources(self.query, self.team)

        # Reads no access-controlled table -> skip the access-control preload
        if queried_resources == set():
            return payload

        if restricted_objects := self._get_object_access_restrictions(queried_resources):
            payload["restricted_objects"] = restricted_objects
        if restricted_resources := self._get_resource_access_restrictions(queried_resources):
            payload["restricted_resources"] = restricted_resources

        return payload

    def _get_object_access_restrictions(self, queried_resources: Optional[set[str]]) -> dict[str, list[str]] | None:
        """Per-resource object IDs the user is denied, scoped to the resources this query reads.
        None for admins / no restrictions."""
        user_access_control = self.user_access_control
        if user_access_control is None:
            return None
        blocked = user_access_control.blocked_resource_ids_by_scope
        if queried_resources is not None:
            blocked = {resource: ids for resource, ids in blocked.items() if resource in queried_resources}
        if not blocked:
            return None
        return {resource: sorted(ids) for resource, ids in sorted(blocked.items())}

    def _get_resource_access_restrictions(self, queried_resources: Optional[set[str]]) -> list[str] | None:
        """Resources the user has no resource-level access to, scoped to the resources this query reads."""
        # user is typed Optional[User] but runtime also passes SyntheticUser (project secret keys)
        # and SharedLinkUser (shared renders); broaden for isinstance.
        user = cast("Optional[User | SyntheticUser | SharedLinkUser]", self.user)

        # Userless runs fail-closed - every access-controlled table is denied.
        if user is None:
            return ["*"] if queried_resources is None else sorted(queried_resources) or None

        # Non-real principals (service tokens, shared-link viewers) are scope-gated on system tables;
        # partition on the readable scopes so a narrower token can't be served a broader principal's
        # cached result. Warehouse scopes are excluded: these principals bypass warehouse access
        # control (see Database.create_for), so warehouse tables are readable for them and listing
        # them as restricted would collide with users who are genuinely denied those resources.
        if not isinstance(user, User):
            if queried_resources is None:
                return ["*"]
            restricted = queried_resources - user.readable_system_table_access_scopes() - WAREHOUSE_ACCESS_SCOPES
            return sorted(restricted) or None

        user_access_control = self.user_access_control
        if user_access_control is None:
            return None
        if queried_resources is None:
            return user_access_control.blocked_resources or None
        # has_resource_access resolves RESOURCE_INHERITANCE_MAP (same predicate the schema filter uses),
        # so a deny on a parent (e.g. customer_analytics) still partitions a child-scoped table (account).
        # Intersecting the raw blocked_resources list would miss inherited denies and leak the cache.
        return (
            sorted(s for s in queried_resources if not user_access_control.has_resource_access(cast(APIScopeObject, s)))
            or None
        )


class QueryRunnerWithHogQLContext(AnalyticsQueryRunner[AR]):
    database: Database
    hogql_context: HogQLContext

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # We create a new context here because we need to access the database
        # below in the to_query method and creating a database is pretty heavy
        # so we'll reuse this database for the query once it eventually runs.
        # The database / context are built with the user known at construction
        # time; if the user changes later (e.g. via run(user=...)), _on_user_changed()
        # rebuilds them so property-level access control sees the right user.
        self._build_hogql_context_for_user(self.user)

    def _build_hogql_context_for_user(self, user: Optional[User]) -> None:
        self.database = Database.create_for(team=self.team, user=user)
        self.hogql_context = HogQLContext(team_id=self.team.pk, database=self.database, user=user)

    def _on_user_changed(self) -> None:
        if self.hogql_context.user is self.user:
            return
        self._build_hogql_context_for_user(self.user)

    @property
    def user_access_control(self) -> Optional[UserAccessControl]:
        # Reuse the instance create_for already preloaded on the database, so the cache fingerprint
        # and schema filtering resolve access from the same rows.
        return self.database.user_access_control


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
