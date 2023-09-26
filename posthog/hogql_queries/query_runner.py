from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Generic, List, Optional, Type, Dict, TypeVar

from prometheus_client import Counter
from django.core.cache import cache
from django.conf import settings
from pydantic import BaseModel, ConfigDict

from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import print_ast
from posthog.hogql.timings import HogQLTimings
from posthog.metrics import LABEL_TEAM_ID
from posthog.models import Team
from posthog.schema import QueryTiming
from posthog.types import InsightQueryNode
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


class CachedQueryResponse(QueryResponse):
    model_config = ConfigDict(
        extra="forbid",
    )
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str


class QueryRunner(ABC):
    query: InsightQueryNode
    query_type: Type[InsightQueryNode]
    team: Team
    timings: HogQLTimings

    def __init__(self, query: InsightQueryNode | Dict[str, Any], team: Team, timings: Optional[HogQLTimings] = None):
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

    @abstractmethod
    def to_persons_query(self) -> str:
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
        return generate_cache_key(f"query_{self.toJSON()}_{self.team.pk}_{self.team.timezone}")

    @abstractmethod
    def _is_stale(self, cached_result_package):
        raise NotImplementedError()

    @abstractmethod
    def _refresh_frequency(self):
        raise NotImplementedError()
