from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Generic, List, Optional, Type, Dict, TypeVar, Union, Tuple, cast

from django.conf import settings
from django.core.cache import cache
from prometheus_client import Counter
from pydantic import BaseModel, ConfigDict

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
    QueryTiming,
    SessionsTimelineQuery,
    TrendsQuery,
    LifecycleQuery,
    WebTopClicksQuery,
    WebOverviewQuery,
    PersonsQuery,
    EventsQuery,
    WebStatsTableQuery,
    HogQLQuery,
    InsightPersonsQuery,
    DashboardFilter,
    HogQLQueryModifiers,
    RetentionQuery,
)
from posthog.utils import generate_cache_key, get_safe_cache

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


class QueryResponse(BaseModel, Generic[DataT]):
    model_config = ConfigDict(
        extra="forbid",
    )
    results: DataT
    timings: Optional[List[QueryTiming]] = None
    types: Optional[List[Union[Tuple[str, str], str]]] = None
    columns: Optional[List[str]] = None
    hogql: Optional[str] = None
    hasMore: Optional[bool] = None


class CachedQueryResponse(QueryResponse):
    model_config = ConfigDict(
        extra="forbid",
    )
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    cache_key: str
    timezone: str


RunnableQueryNode = Union[
    HogQLQuery,
    TrendsQuery,
    LifecycleQuery,
    InsightPersonsQuery,
    EventsQuery,
    PersonsQuery,
    RetentionQuery,
    SessionsTimelineQuery,
    WebOverviewQuery,
    WebTopClicksQuery,
    WebStatsTableQuery,
]


def get_query_runner(
    query: Dict[str, Any] | RunnableQueryNode | BaseModel,
    team: Team,
    timings: Optional[HogQLTimings] = None,
    limit_context: Optional[LimitContext] = None,
    modifiers: Optional[HogQLQueryModifiers] = None,
) -> "QueryRunner":
    kind = None
    if isinstance(query, dict):
        kind = query.get("kind", None)
    elif hasattr(query, "kind"):
        kind = query.kind  # type: ignore
    else:
        raise ValueError(f"Can't get a runner for an unknown query type: {query}")

    if kind == "LifecycleQuery":
        from .insights.lifecycle_query_runner import LifecycleQueryRunner

        return LifecycleQueryRunner(
            query=cast(LifecycleQuery | Dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "TrendsQuery":
        from .insights.trends.trends_query_runner import TrendsQueryRunner

        return TrendsQueryRunner(
            query=cast(TrendsQuery | Dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "RetentionQuery":
        from .insights.retention_query_runner import RetentionQueryRunner

        return RetentionQueryRunner(
            query=cast(RetentionQuery | Dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "EventsQuery":
        from .events_query_runner import EventsQueryRunner

        return EventsQueryRunner(
            query=cast(EventsQuery | Dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "PersonsQuery":
        from .persons_query_runner import PersonsQueryRunner

        return PersonsQueryRunner(
            query=cast(PersonsQuery | Dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "InsightPersonsQuery":
        from .insights.insight_persons_query_runner import InsightPersonsQueryRunner

        return InsightPersonsQueryRunner(
            query=cast(InsightPersonsQuery | Dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "HogQLQuery":
        from .hogql_query_runner import HogQLQueryRunner

        return HogQLQueryRunner(
            query=cast(HogQLQuery | Dict[str, Any], query),
            team=team,
            timings=timings,
            limit_context=limit_context,
            modifiers=modifiers,
        )
    if kind == "SessionsTimelineQuery":
        from .sessions_timeline_query_runner import SessionsTimelineQueryRunner

        return SessionsTimelineQueryRunner(
            query=cast(SessionsTimelineQuery | Dict[str, Any], query),
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


class QueryRunner(ABC):
    query: RunnableQueryNode
    query_type: Type[RunnableQueryNode]
    team: Team
    timings: HogQLTimings
    modifiers: HogQLQueryModifiers
    limit_context: LimitContext

    def __init__(
        self,
        query: RunnableQueryNode | BaseModel | Dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        self.team = team
        self.timings = timings or HogQLTimings()
        self.limit_context = limit_context or LimitContext.QUERY
        self.modifiers = create_default_modifiers_for_team(team, modifiers)
        if isinstance(query, self.query_type):
            self.query = query  # type: ignore
        else:
            self.query = self.query_type.model_validate(query)

    @abstractmethod
    def calculate(self) -> BaseModel:
        # The returned model should have a structure similar to QueryResponse.
        # Due to the way schema.py is generated, we don't have a good inheritance story here.
        raise NotImplementedError()

    def run(self, refresh_requested: Optional[bool] = None) -> CachedQueryResponse:
        cache_key = f"{self._cache_key()}_{self.limit_context or LimitContext.QUERY}"
        tag_queries(cache_key=cache_key)

        if not refresh_requested:
            cached_response = get_safe_cache(cache_key)
            if cached_response:
                if not self._is_stale(cached_response):
                    QUERY_CACHE_HIT_COUNTER.labels(team_id=self.team.pk, cache_hit="hit").inc()
                    cached_response.is_cached = True
                    return cached_response
                else:
                    QUERY_CACHE_HIT_COUNTER.labels(team_id=self.team.pk, cache_hit="stale").inc()
            else:
                QUERY_CACHE_HIT_COUNTER.labels(team_id=self.team.pk, cache_hit="miss").inc()

        fresh_response_dict = cast(QueryResponse, self.calculate()).model_dump()
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
    def to_query(self) -> ast.SelectQuery:
        raise NotImplementedError()

    def to_persons_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
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

    def toJSON(self) -> str:
        return self.query.model_dump_json(exclude_defaults=True, exclude_none=True)

    def _cache_key(self) -> str:
        modifiers = self.modifiers.model_dump_json(exclude_defaults=True, exclude_none=True)
        return generate_cache_key(
            f"query_{self.toJSON()}_{self.__class__.__name__}_{self.team.pk}_{self.team.timezone}_{modifiers}"
        )

    @abstractmethod
    def _is_stale(self, cached_result_package):
        raise NotImplementedError()

    @abstractmethod
    def _refresh_frequency(self):
        raise NotImplementedError()

    def apply_dashboard_filters(self, dashboard_filter: DashboardFilter) -> RunnableQueryNode:
        raise NotImplementedError()
