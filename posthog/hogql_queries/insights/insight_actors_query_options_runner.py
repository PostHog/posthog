from typing import cast

from posthog.schema import (
    CachedInsightActorsQueryOptionsResponse,
    InsightActorsQueryOptions,
    InsightActorsQueryOptionsResponse,
)

from posthog.hogql import ast

from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.hogql_queries.insights.lifecycle.lifecycle_query_runner import LifecycleQueryRunner
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.models.filters.mixins.utils import cached_property


class InsightActorsQueryOptionsRunner(QueryRunner):
    query: InsightActorsQueryOptions
    cached_response: CachedInsightActorsQueryOptionsResponse

    @cached_property
    def source_runner(self) -> QueryRunner:
        # Modifiers must flow through so a cache-only read by the source runner (e.g. funnels)
        # resolves the same cache key as the insight page's own run.
        return get_query_runner(
            self.query.source.source, self.team, self.timings, self.limit_context, self.modifiers, user=self.user
        )

    def validate(self) -> None:
        super().validate()
        self.source_runner.validate()

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        raise ValueError(f"Cannot convert source query of type {self.query.source.kind} to query")

    def _calculate(self) -> InsightActorsQueryOptionsResponse:
        if isinstance(self.source_runner, TrendsQueryRunner):
            trends_runner = cast(TrendsQueryRunner, self.source_runner)
            return trends_runner.to_actors_query_options()
        elif isinstance(self.source_runner, LifecycleQueryRunner):
            lifecycle_runner = cast(LifecycleQueryRunner, self.source_runner)
            return lifecycle_runner.to_actors_query_options()
        elif isinstance(self.source_runner, FunnelsQueryRunner):
            # Only plain FunnelsActorsQuery sources land here — correlation modals wrap a
            # FunnelCorrelationQueryRunner and keep falling through to the empty response.
            funnels_runner = cast(FunnelsQueryRunner, self.source_runner)
            return funnels_runner.to_actors_query_options()

        return InsightActorsQueryOptionsResponse(day=None, status=None, interval=None, breakdown=None, series=None)
