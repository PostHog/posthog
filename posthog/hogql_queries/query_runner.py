from abc import ABC, abstractmethod
from datetime import datetime, timedelta, UTC
from enum import IntEnum
from typing import Any, Generic, Optional, TypeVar, Union, cast, TypeGuard

import structlog
from prometheus_client import Counter
from pydantic import BaseModel, ConfigDict
from sentry_sdk import capture_exception, push_scope, set_tag, get_traceparent

from posthog.caching.utils import is_stale, ThresholdMode, cache_target_age, last_refresh_from_cached_result
from posthog.clickhouse.client.execute_async import enqueue_process_query_task, get_query_status, QueryNotFoundError
from posthog.clickhouse.query_tagging import tag_queries, get_query_tag_value
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import print_ast
from posthog.hogql.query import create_default_modifiers_for_team
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.query_cache import QueryCacheManager
from posthog.metrics import LABEL_TEAM_ID
from posthog.models import Team, User
from posthog.schema import (
    ActorsQuery,
    CacheMissResponse,
    DashboardFilter,
    DateRange,
    EventsQuery,
    FilterLogicalOperator,
    FunnelCorrelationActorsQuery,
    FunnelCorrelationQuery,
    FunnelsActorsQuery,
    FunnelsQuery,
    HogQLQuery,
    HogQLQueryModifiers,
    InsightActorsQuery,
    InsightActorsQueryOptions,
    LifecycleQuery,
    PathsQuery,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    QueryTiming,
    RetentionQuery,
    SamplingRate,
    SessionsTimelineQuery,
    StickinessQuery,
    TrendsQuery,
    WebOverviewQuery,
    WebStatsTableQuery,
    WebTopClicksQuery,
    QueryStatusResponse,
    GenericCachedQueryResponse,
    QueryStatus,
    SessionAttributionExplorerQuery,
)
from posthog.schema_helpers import to_dict, to_json
from posthog.utils import generate_cache_key, get_from_dict_or_attr

logger = structlog.get_logger(__name__)

QUERY_CACHE_WRITE_COUNTER = Counter(
    "posthog_query_cache_write_total",
    "When a query result was persisted in the cache.",
    labelnames=[LABEL_TEAM_ID],
)

QUERY_CACHE_HIT_COUNTER = Counter(
    "posthog_query_cache_hit_total",
    "Whether we could fetch the query from the cache or not.",
    labelnames=[LABEL_TEAM_ID, "cache_hit", "trigger"],
)

EXTENDED_CACHE_AGE = timedelta(days=1)


class ExecutionMode(IntEnum):  # Keep integer values the same for Celery's sake
    CALCULATE_BLOCKING_ALWAYS = 5
    """Always recalculate."""
    CALCULATE_ASYNC_ALWAYS = 4
    """Always kick off async calculation."""
    RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE = 3
    """Use cache, unless the results are missing or stale."""
    RECENT_CACHE_CALCULATE_ASYNC_IF_STALE = 2
    """Use cache, kick off async calculation when results are missing or stale."""
    EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE = 1
    """Use cache for longer, kick off async calculation when results are missing or stale."""
    CACHE_ONLY_NEVER_CALCULATE = 0
    """Do not initiate calculation."""


def execution_mode_from_refresh(refresh_requested: bool | str | None) -> ExecutionMode:
    refresh_map = {
        "blocking": ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
        "async": ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE,
        "lazy_async": ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE,
        "force_async": ExecutionMode.CALCULATE_ASYNC_ALWAYS,
        "force_blocking": ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
        "force_cache": ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
        True: ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
    }
    if refresh_requested in refresh_map:
        return refresh_map[refresh_requested]
    return ExecutionMode.CACHE_ONLY_NEVER_CALCULATE


def shared_insights_execution_mode(execution_mode: ExecutionMode) -> ExecutionMode:
    shared_mode_whitelist = {
        # Cache only is default refresh mode - remap to async so shared insights stay fresh
        ExecutionMode.CACHE_ONLY_NEVER_CALCULATE: ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE,
        # Legacy refresh=true - but on shared insights, we don't give the ability to refresh at will
        # TODO: Adjust once shared insights can poll for async query_status
        ExecutionMode.CALCULATE_BLOCKING_ALWAYS: ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
        # Allow regular async
        ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE: ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE,
        # - All others fall back to extended cache -
    }
    return shared_mode_whitelist.get(execution_mode, ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE)


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
    SessionAttributionExplorerQuery,
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
        from .insights.insight_actors_query_options_runner import (
            InsightActorsQueryOptionsRunner,
        )

        return InsightActorsQueryOptionsRunner(
            query=cast(InsightActorsQueryOptions | dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "FunnelCorrelationQuery":
        from .insights.funnels.funnel_correlation_query_runner import (
            FunnelCorrelationQueryRunner,
        )

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
    if kind == "WebTopClicksQuery":
        from .web_analytics.top_clicks import WebTopClicksQueryRunner

        return WebTopClicksQueryRunner(
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

    if kind == "SessionAttributionExplorerQuery":
        from .web_analytics.session_attribution_explorer_query_runner import SessionAttributionExplorerQueryRunner

        return SessionAttributionExplorerQueryRunner(
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

    def __init__(
        self,
        query: Q | BaseModel | dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
        query_id: Optional[str] = None,
    ):
        self.team = team
        self.timings = timings or HogQLTimings()
        self.limit_context = limit_context or LimitContext.QUERY
        _modifiers = modifiers or (query.modifiers if hasattr(query, "modifiers") else None)
        self.modifiers = create_default_modifiers_for_team(team, _modifiers)
        self.query_id = query_id

        if not self.is_query_node(query):
            query = self.query_type.model_validate(query)
        assert isinstance(query, self.query_type)
        self.query = query

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

    @abstractmethod
    def calculate(self) -> R:
        raise NotImplementedError()

    def enqueue_async_calculation(
        self,
        *,
        cache_manager: QueryCacheManager,
        refresh_requested: bool = False,
        user: Optional[User] = None,
    ) -> QueryStatus:
        return enqueue_process_query_task(
            team=self.team,
            user_id=user.id if user else None,
            insight_id=cache_manager.insight_id,
            dashboard_id=cache_manager.dashboard_id,
            query_json=self.query.model_dump(),
            query_id=self.query_id or cache_manager.cache_key,  # Use cache key as query ID to avoid duplicates
            refresh_requested=refresh_requested,
        )

    def get_async_query_status(self, *, cache_key: str) -> Optional[QueryStatus]:
        try:
            query_status = get_query_status(team_id=self.team.pk, query_id=self.query_id or cache_key)
            if query_status.complete:
                return None
            return query_status

        except QueryNotFoundError:
            return None

    def count_query_cache_hit(self, hit: str, trigger: str = "") -> None:
        if (get_query_tag_value("trigger") or "").startswith("warming"):
            # We don't want to count for cache hits caused by warming itself
            return
        QUERY_CACHE_HIT_COUNTER.labels(team_id=self.team.pk, cache_hit=hit, trigger=trigger).inc()

    def handle_cache_and_async_logic(
        self, execution_mode: ExecutionMode, cache_manager: QueryCacheManager, user: Optional[User] = None
    ) -> Optional[CR | CacheMissResponse]:
        CachedResponse: type[CR] = self.cached_response_type
        cached_response: CR | CacheMissResponse
        cached_response_candidate = cache_manager.get_cache_data()

        if self.is_cached_response(cached_response_candidate):
            cached_response_candidate["is_cached"] = True
            cached_response = CachedResponse(**cached_response_candidate)
        elif cached_response_candidate is None:
            cached_response = CacheMissResponse(cache_key=cache_manager.cache_key)
        else:
            # Whatever's in cache is malformed, so let's treat is as non-existent
            cached_response = CacheMissResponse(cache_key=cache_manager.cache_key)
            with push_scope() as scope:
                scope.set_tag("cache_key", cache_manager.cache_key)
                capture_exception(
                    ValueError(f"Cached response is of unexpected type {type(cached_response)}, ignoring it")
                )

        if self.is_cached_response(cached_response_candidate):
            assert isinstance(cached_response, CachedResponse)

            if not self._is_stale(last_refresh=last_refresh_from_cached_result(cached_response)):
                self.count_query_cache_hit(hit="hit", trigger=cached_response.calculation_trigger or "")
                # We have a valid result that's fresh enough, let's return it
                cached_response.query_status = self.get_async_query_status(cache_key=cache_manager.cache_key)
                return cached_response

            self.count_query_cache_hit(hit="stale", trigger=cached_response.calculation_trigger or "")
            # We have a stale result. If we aren't allowed to calculate, let's still return it
            # – otherwise let's proceed to calculation
            if execution_mode == ExecutionMode.CACHE_ONLY_NEVER_CALCULATE:
                cached_response.query_status = self.get_async_query_status(cache_key=cache_manager.cache_key)
                return cached_response
            elif execution_mode == ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE:
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
            self.count_query_cache_hit(hit="miss", trigger="")
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
        cache_key = self.get_cache_key()

        tag_queries(cache_key=cache_key)
        tag_queries(sentry_trace=get_traceparent())
        set_tag("cache_key", cache_key)
        set_tag("query_type", self.query.__name__)
        if insight_id:
            tag_queries(insight_id=insight_id)
            set_tag("insight_id", str(insight_id))
        if dashboard_id:
            tag_queries(dashboard_id=dashboard_id)
            set_tag("dashboard_id", str(dashboard_id))

        self.query_id = query_id or self.query_id
        CachedResponse: type[CR] = self.cached_response_type
        cache_manager = QueryCacheManager(
            team_id=self.team.pk,
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
            if results is not None:
                return results

        last_refresh = datetime.now(UTC)
        target_age = self.cache_target_age(last_refresh=last_refresh)
        fresh_response_dict = {
            **self.calculate().model_dump(),
            "is_cached": False,
            "last_refresh": last_refresh,
            "next_allowed_client_refresh": last_refresh + self._refresh_frequency(),
            "cache_key": cache_key,
            "timezone": self.team.timezone,
            "cache_target_age": target_age,
        }
        if get_query_tag_value("trigger"):
            fresh_response_dict["calculation_trigger"] = get_query_tag_value("trigger")
        fresh_response = CachedResponse(**fresh_response_dict)

        # Don't cache debug queries with errors and export queries
        has_error: Optional[list] = fresh_response_dict.get("error", None)
        if (has_error is None or len(has_error) == 0) and self.limit_context != LimitContext.EXPORT:
            cache_manager.set_cache_data(
                response=fresh_response_dict,
                # This would be a possible place to decide to not ever keep this cache warm
                # Example: Not for super quickly calculated insights
                # Set target_age to None in that case
                target_age=target_age,
            )
            QUERY_CACHE_WRITE_COUNTER.labels(team_id=self.team.pk).inc()

        return fresh_response

    @abstractmethod
    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        raise NotImplementedError()

    def to_actors_query(self, *args, **kwargs) -> ast.SelectQuery | ast.SelectUnionQuery:
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

    def get_cache_payload(self) -> dict:
        return {
            "query_runner": self.__class__.__name__,
            "query": to_dict(self.query),
            "team_id": self.team.pk,
            "hogql_modifiers": to_dict(self.modifiers),
            "limit_context": self._limit_context_aliased_for_cache,
            "timezone": self.team.timezone,
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

    def _is_stale(self, last_refresh: Optional[datetime], lazy: bool = False) -> bool:
        query_date_range = getattr(self, "query_date_range", None)
        date_to = query_date_range.date_to() if query_date_range else None
        interval = query_date_range.interval_name if query_date_range else "minute"
        mode = ThresholdMode.LAZY if lazy else ThresholdMode.DEFAULT
        return is_stale(self.team, date_to=date_to, interval=interval, last_refresh=last_refresh, mode=mode)

    def _refresh_frequency(self) -> timedelta:
        return timedelta(minutes=1)

    def apply_dashboard_filters(self, dashboard_filter: DashboardFilter):
        """Irreversably update self.query with provided dashboard filters."""
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
