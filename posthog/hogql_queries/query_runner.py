from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Generic, List, Optional, Type, Dict, TypeVar, Union, Tuple, cast

from django.conf import settings
from django.core.cache import cache
from prometheus_client import Counter
from pydantic import BaseModel, ConfigDict

from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import print_ast
from posthog.hogql.timings import HogQLTimings
from posthog.metrics import LABEL_TEAM_ID
from posthog.models import Team
from posthog.schema import (
    QueryTiming,
    TrendsQuery,
    LifecycleQuery,
    WebTopSourcesQuery,
    WebTopClicksQuery,
    WebTopPagesQuery,
    WebOverviewStatsQuery,
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
    result: DataT
    timings: Optional[List[QueryTiming]] = None
    types: Optional[List[Tuple[str, str]]] = None
    columns: Optional[List[str]] = None


class CachedQueryResponse(QueryResponse):
    model_config = ConfigDict(
        extra="forbid",
    )
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str


RunnableQueryNode = Union[
    TrendsQuery,
    LifecycleQuery,
    WebOverviewStatsQuery,
    WebTopSourcesQuery,
    WebTopClicksQuery,
    WebTopPagesQuery,
]


def get_query_runner(
    query: Dict[str, Any] | RunnableQueryNode, team: Team, timings: Optional[HogQLTimings] = None
) -> "QueryRunner":
    kind = None
    if isinstance(query, dict):
        kind = query.get("kind", None)
    elif hasattr(query, "kind"):
        kind = query.kind

    if kind == "LifecycleQuery":
        from .insights.lifecycle_query_runner import LifecycleQueryRunner

        return LifecycleQueryRunner(query=cast(LifecycleQuery | Dict[str, Any], query), team=team, timings=timings)
    if kind == "TrendsQuery":
        from .insights.trends_query_runner import TrendsQueryRunner

        return TrendsQueryRunner(query=cast(TrendsQuery | Dict[str, Any], query), team=team, timings=timings)
    if kind == "WebOverviewStatsQuery":
        from .web_analytics.overview_stats import WebOverviewStatsQueryRunner

        return WebOverviewStatsQueryRunner(query=query, team=team, timings=timings)
    if kind == "WebTopSourcesQuery":
        from .web_analytics.top_sources import WebTopSourcesQueryRunner

        return WebTopSourcesQueryRunner(query=query, team=team, timings=timings)
    if kind == "WebTopClicksQuery":
        from .web_analytics.top_clicks import WebTopClicksQueryRunner

        return WebTopClicksQueryRunner(query=query, team=team, timings=timings)
    if kind == "WebTopPagesQuery":
        from .web_analytics.top_pages import WebTopPagesQueryRunner

        return WebTopPagesQueryRunner(query=query, team=team, timings=timings)

    raise ValueError(f"Can't get a runner for an unknown query kind: {kind}")


class QueryRunner(ABC):
    query: RunnableQueryNode
    query_type: Type[RunnableQueryNode]
    team: Team
    timings: HogQLTimings

    def __init__(self, query: RunnableQueryNode | Dict[str, Any], team: Team, timings: Optional[HogQLTimings] = None):
        self.team = team
        self.timings = timings or HogQLTimings()
        if isinstance(query, self.query_type):
            self.query = query  # type: ignore
        else:
            self.query = self.query_type.model_validate(query)

    @abstractmethod
    def calculate(self) -> QueryResponse:
        raise NotImplementedError()

    def run(self, refresh_requested: bool) -> CachedQueryResponse:
        cache_key = self._cache_key()
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

        fresh_response_dict = self.calculate().model_dump()
        fresh_response_dict["is_cached"] = False
        fresh_response_dict["last_refresh"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        fresh_response_dict["next_allowed_client_refresh"] = (datetime.now() + self._refresh_frequency()).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        fresh_response = CachedQueryResponse(**fresh_response_dict)
        cache.set(cache_key, fresh_response, settings.CACHED_RESULTS_TTL)
        QUERY_CACHE_WRITE_COUNTER.labels(team_id=self.team.pk).inc()
        return fresh_response

    @abstractmethod
    def to_query(self) -> ast.SelectQuery:
        raise NotImplementedError()

    def to_persons_query(self) -> ast.SelectQuery:
        # TODO: add support for selecting and filtering by breakdowns
        raise NotImplementedError()

    def to_hogql(self) -> str:
        with self.timings.measure("to_hogql"):
            return print_ast(
                self.to_query(),
                HogQLContext(team_id=self.team.pk, enable_select_queries=True, timings=self.timings),
                "hogql",
            )

    def toJSON(self) -> str:
        return self.query.model_dump_json(exclude_defaults=True, exclude_none=True)

    def _cache_key(self) -> str:
        return generate_cache_key(
            f"query_{self.toJSON()}_{self.__class__.__name__}_{self.team.pk}_{self.team.timezone}"
        )

    @abstractmethod
    def _is_stale(self, cached_result_package):
        raise NotImplementedError()

    @abstractmethod
    def _refresh_frequency(self):
        raise NotImplementedError()
