from typing import cast, Optional

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.funnels.funnel_correlation_query_runner import FunnelCorrelationQueryRunner
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.hogql_queries.insights.lifecycle_query_runner import LifecycleQueryRunner
from posthog.hogql_queries.insights.retention_query_runner import RetentionQueryRunner
from posthog.hogql_queries.insights.stickiness_query_runner import StickinessQueryRunner
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    FunnelCorrelationActorsQuery,
    FunnelCorrelationQuery,
    FunnelsActorsQuery,
    InsightActorsQuery,
    HogQLQueryResponse,
    StickinessQuery,
    TrendsQuery,
    FunnelsQuery,
    LifecycleQuery,
    InsightEventsQuery,
    ActorsQueryResponse,
    CachedActorsQueryResponse,
)


class InsightEventsQueryRunner(QueryRunner):
    query: InsightEventsQuery
    response: ActorsQueryResponse
    cached_response: CachedActorsQueryResponse

    @cached_property
    def source_runner(self) -> QueryRunner:
        return get_query_runner(self.query.source, self.team, self.timings, self.limit_context, self.modifiers)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        if isinstance(self.source_runner, TrendsQueryRunner):
            trends_runner = cast(TrendsQueryRunner, self.source_runner)
            query = cast(InsightActorsQuery, self.query)
            return trends_runner.to_events_query(
                time_frame=cast(Optional[str], query.day),  # Other runner accept day as int, but not this one
                series_index=query.series or 0,
                breakdown_value=query.breakdown,
                compare_value=query.compare,
            )

        raise ValueError(f"Cannot convert source query of type {self.query.source.kind} to events query")

    def to_actors_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return self.to_query()

    @property
    def group_type_index(self) -> int | None:
        if isinstance(self.source_runner, RetentionQueryRunner):
            return cast(RetentionQueryRunner, self.source_runner).group_type_index

        if isinstance(self.source_runner, FunnelCorrelationQueryRunner):
            assert isinstance(self.query, FunnelCorrelationActorsQuery)
            assert isinstance(self.query.source, FunnelCorrelationQuery)
            return self.query.source.source.source.aggregation_group_type_index

        if isinstance(self.source_runner, FunnelsQueryRunner):
            assert isinstance(self.query, FunnelsActorsQuery)
            assert isinstance(self.query.source, FunnelsQuery)
            return self.query.source.aggregation_group_type_index

        if isinstance(self.source_runner, LifecycleQueryRunner):
            # Lifecycle Query uses a plain InsightActorsQuery
            assert isinstance(self.query.source, LifecycleQuery)
            return self.query.source.aggregation_group_type_index

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
        settings = None

        return execute_hogql_query(
            query_type="InsightEventsQuery",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            settings=settings,
        )
