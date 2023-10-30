from datetime import timedelta
from typing import Dict, Optional, Any, cast

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.lifecycle_query_runner import LifecycleQueryRunner
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.models import Team
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import InsightPersonsQuery, HogQLQueryResponse


class InsightPersonsQueryRunner(QueryRunner):
    query: InsightPersonsQuery
    query_type = InsightPersonsQuery

    def __init__(
        self,
        query: InsightPersonsQuery | Dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        in_export_context: Optional[bool] = False,
    ):
        super().__init__(query, team, timings, in_export_context)
        if isinstance(query, InsightPersonsQuery):
            self.query = query
        else:
            self.query = InsightPersonsQuery.model_validate(query)

    @cached_property
    def source_runner(self) -> QueryRunner:
        return get_query_runner(self.query.source, self.team, self.timings, self.in_export_context)

    def to_query(self) -> ast.SelectQuery:
        if isinstance(self.source_runner, LifecycleQueryRunner):
            lifecycle_runner = cast(LifecycleQueryRunner, self.source_runner)
            day = self.query.day
            status = self.query.status
            return lifecycle_runner.to_persons_query(day=day, status=status)

        raise ValueError(f"Cannot convert source query of type {self.query.source.kind} to persons query")

    def to_persons_query(self) -> ast.SelectQuery:
        return self.to_query()

    def calculate(self) -> HogQLQueryResponse:
        return execute_hogql_query(
            query_type="InsightPersonsQuery",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
        )

    def _is_stale(self, cached_result_package):
        return True

    def _refresh_frequency(self):
        return timedelta(minutes=1)
