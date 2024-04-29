from abc import ABC, abstractmethod
from datetime import datetime
from enum import IntEnum
from typing import Any, Generic, Optional, TypeVar, Union, cast, TypeGuard

from django.conf import settings
from django.core.cache import cache
from prometheus_client import Counter
from pydantic import BaseModel, ConfigDict
from sentry_sdk import capture_exception, push_scope
import structlog

from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import print_ast
from posthog.hogql.query import create_default_modifiers_for_team
from posthog.hogql.timings import HogQLTimings
from posthog.metrics import LABEL_TEAM_ID
from posthog.models import Team
from posthog.schema import (
    DateRange,
    FilterLogicalOperator,
    FunnelCorrelationActorsQuery,
    FunnelCorrelationQuery,
    FunnelsActorsQuery,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    TrendsQuery,
    FunnelsQuery,
    RetentionQuery,
    PathsQuery,
    StickinessQuery,
    LifecycleQuery,
    HogQLQuery,
    WebOverviewQuery,
    WebTopClicksQuery,
    WebStatsTableQuery,
    QueryTiming,
    SessionsTimelineQuery,
    ActorsQuery,
    EventsQuery,
    InsightActorsQuery,
    DashboardFilter,
    HogQLQueryModifiers,
    SamplingRate,
    InsightActorsQueryOptions,
)
from posthog.utils import generate_cache_key, get_safe_cache

logger = structlog.get_logger(__name__)

QUERY_CACHE_WRITE_COUNTER = Counter(
    "posthog_query_cache_write_total",
    "When a query result was persisted in the cache.",
    labelnames=[LABEL_TEAM_ID],
)

QUERY_CACHE_HIT_COUNTER = Counter(
    "posthog_query_cache_hit_total",
    "Whether we could fetch the query from the cache or not.",
    labelnames=[LABEL_TEAM_ID, "cache_hit"],
)

DataT = TypeVar("DataT")


class ExecutionMode(IntEnum):
    CALCULATION_ALWAYS = 2
    """Always recalculate."""
    RECENT_CACHE_CALCULATE_IF_STALE = 1
    """Use cache, unless the results are missing or stale."""
    CACHE_ONLY_NEVER_CALCULATE = 0
    """Do not initiate calculation."""


class QueryResponse(BaseModel, Generic[DataT]):
    model_config = ConfigDict(
        extra="forbid",
    )
    results: DataT
    timings: Optional[list[QueryTiming]] = None
    types: Optional[list[Union[tuple[str, str], str]]] = None
    columns: Optional[list[str]] = None
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


class CacheMissResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: Optional[str]


RunnableQueryNode = Union[
    TrendsQuery,
    FunnelsQuery,
    RetentionQuery,
    PathsQuery,
    StickinessQuery,
    LifecycleQuery,
    ActorsQuery,
    EventsQuery,
    HogQLQuery,
    InsightActorsQuery,
    FunnelsActorsQuery,
    FunnelCorrelationQuery,
    FunnelCorrelationActorsQuery,
    InsightActorsQueryOptions,
    SessionsTimelineQuery,
    WebOverviewQuery,
    WebStatsTableQuery,
    WebTopClicksQuery,
]


def get_query_runner(
    query: dict[str, Any] | RunnableQueryNode | BaseModel,
    team: Team,
    timings: Optional[HogQLTimings] = None,
    limit_context: Optional[LimitContext] = None,
    modifiers: Optional[HogQLQueryModifiers] = None,
) -> "QueryRunner":
    kind = None
    if isinstance(query, dict):
        kind = query.get("kind", None)
    elif hasattr(query, "kind"):
        kind = query.kind
    else:
        raise ValueError(f"Can't get a runner for an unknown query type: {query}")

    if kind == "TrendsQuery":
        from .insights.trends.trends_query_runner import TrendsQueryRunner

        return TrendsQueryRunner(
            query=cast(TrendsQuery | dict[str, Any], query),
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
    if kind == "ActorsQuery":
        from .actors_query_runner import ActorsQueryRunner

        return ActorsQueryRunner(
            query=cast(ActorsQuery | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "InsightActorsQuery" or kind == "FunnelsActorsQuery" or kind == "FunnelCorrelationActorsQuery":
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
    if kind == "HogQLQuery":
        from .hogql_query_runner import HogQLQueryRunner

        return HogQLQueryRunner(
            query=cast(HogQLQuery | dict[str, Any], query),
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
        )
    if kind == "WebOverviewQuery":
        from .web_analytics.web_overview import WebOverviewQueryRunner

        return WebOverviewQueryRunner(query=query, team=team, timings=timings, modifiers=modifiers)
    if kind == "WebTopClicksQuery":
        from .web_analytics.top_clicks import WebTopClicksQueryRunner

        return WebTopClicksQueryRunner(query=query, team=team, timings=timings, modifiers=modifiers)
    if kind == "WebStatsTableQuery":
        from .web_analytics.stats_table import WebStatsTableQueryRunner

        return WebStatsTableQueryRunner(query=query, team=team, timings=timings, modifiers=modifiers)

    raise ValueError(f"Can't get a runner for an unknown query kind: {kind}")


Q = TypeVar("Q", bound=RunnableQueryNode)
# R (for Response) should have a structure similar to QueryResponse.
# Due to the way schema.py is generated, we don't have a good inheritance story here.
R = TypeVar("R", bound=BaseModel)


class QueryRunner(ABC, Generic[Q, R]):
    query: Q

    team: Team
    timings: HogQLTimings
    modifiers: HogQLQueryModifiers
    limit_context: LimitContext

    def __init__(
        self,
        query: Q | BaseModel | dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        self.team = team
        self.timings = timings or HogQLTimings()
        self.limit_context = limit_context or LimitContext.QUERY
        _modifiers = modifiers or (query.modifiers if hasattr(query, "modifiers") else None)
        self.modifiers = create_default_modifiers_for_team(team, _modifiers)

        if not self.is_query_node(query):
            query = self.query_type.model_validate(query)
        assert isinstance(query, self.query_type)
        self.query = query

    @property
    def query_type(self) -> type[Q]:
        return self.__annotations__["query"]  # Enforcing the type annotation of `query` at runtime

    def is_query_node(self, data) -> TypeGuard[Q]:
        return isinstance(data, self.query_type)

    @abstractmethod
    def calculate(self) -> R:
        raise NotImplementedError()

    def run(
        self, execution_mode: ExecutionMode = ExecutionMode.RECENT_CACHE_CALCULATE_IF_STALE
    ) -> CachedQueryResponse | CacheMissResponse:
        # TODO: `self.limit_context` should probably just be in get_cache_key()
        cache_key = cache_key = f"{self.get_cache_key()}_{self.limit_context or LimitContext.QUERY}"
        tag_queries(cache_key=cache_key)

        if execution_mode != ExecutionMode.CALCULATION_ALWAYS:
            # Let's look in the cache first
            cached_response: CachedQueryResponse | CacheMissResponse
            cached_response_candidate = get_safe_cache(cache_key)
            match cached_response_candidate:
                case CachedQueryResponse():
                    cached_response = cached_response_candidate
                    cached_response_candidate.is_cached = True
                case None:
                    cached_response = CacheMissResponse(cache_key=cache_key)
                case _:
                    # Whatever's in cache is malformed, so let's treat is as non-existent
                    cached_response = CacheMissResponse(cache_key=cache_key)
                    with push_scope() as scope:
                        scope.set_tag("cache_key", cache_key)
                        capture_exception(
                            ValueError(f"Cached response is of unexpected type {type(cached_response)}, ignoring it")
                        )

            if isinstance(cached_response, CachedQueryResponse):
                if not self._is_stale(cached_response):
                    QUERY_CACHE_HIT_COUNTER.labels(team_id=self.team.pk, cache_hit="hit").inc()
                    # We have a valid result that's fresh enough, let's return it
                    return cached_response
                else:
                    QUERY_CACHE_HIT_COUNTER.labels(team_id=self.team.pk, cache_hit="stale").inc()
                    # We have a stale result. If we aren't allowed to calculate, let's still return it
                    # – otherwise let's proceed to calculation
                    if execution_mode == ExecutionMode.CACHE_ONLY_NEVER_CALCULATE:
                        return cached_response
            else:
                QUERY_CACHE_HIT_COUNTER.labels(team_id=self.team.pk, cache_hit="miss").inc()
                # We have no cached result. If we aren't allowed to calculate, let's return the cache miss
                # – otherwise let's proceed to calculation
                if execution_mode == ExecutionMode.CACHE_ONLY_NEVER_CALCULATE:
                    return cached_response

        fresh_response_dict = self.calculate().model_dump()
        fresh_response_dict["is_cached"] = False
        fresh_response_dict["last_refresh"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        fresh_response_dict["next_allowed_client_refresh"] = (datetime.now() + self._refresh_frequency()).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        fresh_response_dict["cache_key"] = cache_key
        fresh_response_dict["timezone"] = self.team.timezone
        fresh_response = CachedQueryResponse(**fresh_response_dict)
        cache.set(cache_key, fresh_response, settings.CACHED_RESULTS_TTL)
        QUERY_CACHE_WRITE_COUNTER.labels(team_id=self.team.pk).inc()
        return fresh_response

    @abstractmethod
    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        raise NotImplementedError()

    def to_actors_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        # TODO: add support for selecting and filtering by breakdowns
        raise NotImplementedError()

    def to_hogql(self) -> str:
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
            )

    def to_json(self) -> str:
        return self.query.model_dump_json(exclude_defaults=True, exclude_none=True)

    def get_cache_key(self) -> str:
        modifiers = self.modifiers.model_dump_json(exclude_defaults=True, exclude_none=True)
        return generate_cache_key(
            f"query_{self.to_json()}_{self.__class__.__name__}_{self.team.pk}_{self.team.timezone}_{modifiers}"
        )

    @abstractmethod
    def _is_stale(self, cached_result_package):
        raise NotImplementedError()

    @abstractmethod
    def _refresh_frequency(self):
        raise NotImplementedError()

    def apply_dashboard_filters(self, dashboard_filter: DashboardFilter) -> Q:
        # The default logic below applies to all insights and a lot of other queries
        # Notable exception: `HogQLQuery`, which has `properties` and `dateRange` within `HogQLFilters`
        if hasattr(self.query, "properties") and hasattr(self.query, "dateRange"):
            query_update: dict[str, Any] = {}
            if dashboard_filter.properties:
                if self.query.properties:
                    try:
                        query_update["properties"] = PropertyGroupFilter(
                            type=FilterLogicalOperator.AND,
                            values=[
                                PropertyGroupFilterValue(type=FilterLogicalOperator.AND, values=self.query.properties)
                                if isinstance(self.query.properties, list)
                                else PropertyGroupFilterValue(**self.query.properties.model_dump()),
                                PropertyGroupFilterValue(
                                    type=FilterLogicalOperator.AND, values=dashboard_filter.properties
                                ),
                            ],
                        )
                    except Exception:
                        # If pydantic is unhappy about the shape of data, let's ignore property filters and carry on
                        capture_exception()
                        logger.exception("Failed to apply dashboard property filters")
                else:
                    query_update["properties"] = dashboard_filter.properties
            if dashboard_filter.date_from or dashboard_filter.date_to:
                date_range_update = {}
                if dashboard_filter.date_from:
                    date_range_update["date_from"] = dashboard_filter.date_from
                if dashboard_filter.date_to:
                    date_range_update["date_to"] = dashboard_filter.date_to
                if self.query.dateRange:
                    query_update["dateRange"] = self.query.dateRange.model_copy(update=date_range_update)
                else:
                    query_update["dateRange"] = DateRange(**date_range_update)
            return cast(Q, self.query.model_copy(update=query_update))  # Shallow copy!

        raise NotImplementedError(f"{self.query.__class__.__name__} does not support dashboard filters out of the box")
