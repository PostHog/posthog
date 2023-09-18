from abc import ABC, abstractmethod
from typing import Any, Optional, Type, Dict

from prometheus_client import Counter
from django.utils.timezone import now
from django.core.cache import cache
from django.conf import settings

from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import print_ast
from posthog.hogql.timings import HogQLTimings
from posthog.metrics import LABEL_TEAM_ID
from posthog.models import Team
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


class QueryRunner(ABC):
    query: InsightQueryNode
    query_type: Type[InsightQueryNode]
    team: Team
    timings: HogQLTimings

    def __init__(self, query: InsightQueryNode | Dict[str, Any], team: Team, timings: Optional[HogQLTimings] = None):
        self.team = team
        self.timings = timings or HogQLTimings()
        if isinstance(query, self.query_type):
            self.query = query
        else:
            self.query = self.query_type.model_validate(query)

    @abstractmethod
    def run(self) -> InsightQueryNode:
        raise NotImplementedError()

    def run_cached(self, refresh_requested: bool) -> InsightQueryNode:
        cache_key = self.cache_key()
        tag_queries(cache_key=cache_key)

        if not refresh_requested:
            cached_result_package = get_safe_cache(cache_key)

            if cached_result_package and cached_result_package.result:
                if not self.is_stale(cached_result_package):
                    cached_result_package.is_cached = True
                    QUERY_CACHE_HIT_COUNTER.labels(team_id=self.team.pk, cache_hit="hit").inc()
                    return cached_result_package
                else:
                    QUERY_CACHE_HIT_COUNTER.labels(team_id=self.team.pk, cache_hit="stale").inc()
            else:
                QUERY_CACHE_HIT_COUNTER.labels(team_id=self.team.pk, cache_hit="miss").inc()

        fresh_result_package = self.run()
        fresh_result_package.last_refresh = now()
        fresh_result_package.is_cached = False
        cache.set(cache_key, fresh_result_package, settings.CACHED_RESULTS_TTL)
        QUERY_CACHE_WRITE_COUNTER.labels(team_id=self.team.pk).inc()

        return fresh_result_package

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

    def cache_key(self, cache_invalidation_key: Optional[str] = None):
        payload = f"query_{self.query.kind}_{self.toJSON()}_{self.team.pk}"
        if cache_invalidation_key:
            payload += f"_{cache_invalidation_key}"

        return generate_cache_key(payload)

    @abstractmethod
    def is_stale(self, cached_result_package):
        raise NotImplementedError()
