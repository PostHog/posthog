from datetime import timedelta
from typing import cast

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.hogql_queries.insights.lifecycle_query_runner import LifecycleQueryRunner
from posthog.hogql_queries.insights.paths_query_runner import PathsQueryRunner
from posthog.hogql_queries.insights.retention_query_runner import RetentionQueryRunner
from posthog.hogql_queries.insights.stickiness_query_runner import StickinessQueryRunner
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import FunnelsActorsQuery, InsightActorsQuery, HogQLQueryResponse, StickinessQuery, TrendsQuery
from posthog.types import InsightActorsQueryNode


class InsightActorsQueryRunner(QueryRunner):
    query: InsightActorsQueryNode
    query_type = InsightActorsQueryNode  # type: ignore

    @cached_property
    def source_runner(self) -> QueryRunner:
        return get_query_runner(self.query.source, self.team, self.timings, self.limit_context)

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        if isinstance(self.source_runner, TrendsQueryRunner):
            trends_runner = cast(TrendsQueryRunner, self.source_runner)
            query = cast(InsightActorsQuery, self.query)
            return trends_runner.to_actors_query(
                time_frame=query.day,
                series_index=query.series or 0,
                breakdown_value=query.breakdown,
                compare=query.compare,
            )
        elif isinstance(self.source_runner, FunnelsQueryRunner):
            funnels_runner = cast(FunnelsQueryRunner, self.source_runner)
            funnels_runner.context.actorsQuery = cast(FunnelsActorsQuery, self.query)
            return funnels_runner.to_actors_query()
        elif isinstance(self.source_runner, RetentionQueryRunner):
            query = cast(InsightActorsQuery, self.query)
            retention_runner = cast(RetentionQueryRunner, self.source_runner)
            return retention_runner.to_actors_query(interval=query.interval)
        elif isinstance(self.source_runner, PathsQueryRunner):
            paths_runner = cast(PathsQueryRunner, self.source_runner)
            return paths_runner.to_actors_query()
        elif isinstance(self.source_runner, StickinessQueryRunner):
            stickiness_runner = cast(StickinessQueryRunner, self.source_runner)
            query = cast(InsightActorsQuery, self.query)
            return stickiness_runner.to_actors_query(interval_num=int(query.day) if query.day is not None else None)
        elif isinstance(self.source_runner, LifecycleQueryRunner):
            lifecycle_runner = cast(LifecycleQueryRunner, self.source_runner)
            query = cast(InsightActorsQuery, self.query)
            day = query.day
            status = query.status
            return lifecycle_runner.to_actors_query(day=str(day) if day else None, status=status)

        raise ValueError(f"Cannot convert source query of type {self.query.source.kind} to persons query")

    def to_actors_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        return self.to_query()

    @property
    def group_type_index(self) -> int | None:
        if isinstance(self.source_runner, RetentionQueryRunner):
            return cast(RetentionQueryRunner, self.source_runner).group_type_index

        if (
            isinstance(self.source_runner, StickinessQueryRunner) and isinstance(self.query.source, StickinessQuery)
        ) or (isinstance(self.source_runner, TrendsQueryRunner) and isinstance(self.query.source, TrendsQuery)):
            series_index = self.query.series or 0
            if self.query.source.series and series_index < len(self.query.source.series):
                series = self.query.source.series[series_index]
                if series.math_group_type_index is not None:
                    return int(series.math_group_type_index or 0)

        return None

    def calculate(self) -> HogQLQueryResponse:
        return execute_hogql_query(
            query_type="InsightActorsQuery",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )

    def _is_stale(self, cached_result_package):
        return True

    def _refresh_frequency(self):
        return timedelta(minutes=1)
