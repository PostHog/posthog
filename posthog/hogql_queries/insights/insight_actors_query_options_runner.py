from datetime import timedelta
from typing import cast

from posthog.hogql import ast
from posthog.hogql_queries.insights.lifecycle_query_runner import LifecycleQueryRunner
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import InsightActorsQueryOptions, InsightActorsQueryOptionsResponse


class InsightActorsQueryOptionsRunner(QueryRunner):
    query: InsightActorsQueryOptions
    query_type = InsightActorsQueryOptions

    @cached_property
    def source_runner(self) -> QueryRunner:
        return get_query_runner(self.query.source.source, self.team, self.timings, self.limit_context)

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        raise ValueError(f"Cannot convert source query of type {self.query.source.kind} to query")

    def calculate(self) -> InsightActorsQueryOptionsResponse:
        if isinstance(self.source_runner, LifecycleQueryRunner):
            lifecycle_runner = cast(LifecycleQueryRunner, self.source_runner)
            return lifecycle_runner.to_actors_query_options()

        return InsightActorsQueryOptionsResponse(
            day=None,
            status=None,
            interval=None,
        )

    def _is_stale(self, cached_result_package):
        return True

    def _refresh_frequency(self):
        return timedelta(minutes=1)
