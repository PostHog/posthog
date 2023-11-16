from datetime import timedelta
from typing import cast

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.lifecycle_query_runner import LifecycleQueryRunner
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import InsightPersonsQuery, HogQLQueryResponse


class InsightPersonsQueryRunner(QueryRunner):
    query: InsightPersonsQuery
    query_type = InsightPersonsQuery

    @cached_property
    def source_runner(self) -> QueryRunner:
        return get_query_runner(self.query.source, self.team, self.timings, self.in_export_context)

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        if isinstance(self.source_runner, LifecycleQueryRunner):
            lifecycle_runner = cast(LifecycleQueryRunner, self.source_runner)
            day = self.query.day
            status = self.query.status
            return lifecycle_runner.to_persons_query(day=day, status=status)
        elif isinstance(self.source_runner, TrendsQueryRunner):
            trends_runner = cast(TrendsQueryRunner, self.source_runner)
            return trends_runner.to_persons_query()

        raise ValueError(f"Cannot convert source query of type {self.query.source.kind} to persons query")

    def to_persons_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        return self.to_query()

    def calculate(self) -> HogQLQueryResponse:
        return execute_hogql_query(
            query_type="InsightPersonsQuery",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )

    def _is_stale(self, cached_result_package):
        return True

    def _refresh_frequency(self):
        return timedelta(minutes=1)
