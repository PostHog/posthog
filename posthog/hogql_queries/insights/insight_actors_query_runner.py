from typing import Any, Optional, cast

from posthog.schema import (
    FunnelCorrelationActorsQuery,
    FunnelCorrelationQuery,
    FunnelsActorsQuery,
    FunnelsQuery,
    HogQLQueryModifiers,
    HogQLQueryResponse,
    InsightActorsQuery,
    LifecycleQuery,
    StickinessActorsQuery,
    StickinessQuery,
    TrendsQuery,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings

from posthog.hogql_queries.insights.funnels.funnel_correlation_query_runner import FunnelCorrelationQueryRunner
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.hogql_queries.insights.lifecycle_query_runner import LifecycleQueryRunner
from posthog.hogql_queries.insights.paths_query_runner import PathsQueryRunner
from posthog.hogql_queries.insights.retention_query_runner import RetentionQueryRunner
from posthog.hogql_queries.insights.stickiness_query_runner import StickinessQueryRunner
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, QueryRunner, get_query_runner
from posthog.models import Team
from posthog.models.filters.mixins.utils import cached_property
from posthog.types import InsightActorsQueryNode


class InsightActorsQueryRunner(AnalyticsQueryRunner[HogQLQueryResponse]):
    query: InsightActorsQueryNode

    def __init__(
        self,
        query: InsightActorsQueryNode | dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
        query_id: Optional[str] = None,
    ):
        super().__init__(
            query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            query_id=query_id,
            extract_modifiers=lambda query: query.source.modifiers if hasattr(query.source, "modifiers") else None,
        )

    @cached_property
    def source_runner(self) -> QueryRunner:
        return get_query_runner(self.query.source, self.team, self.timings, self.limit_context, self.modifiers)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        if isinstance(self.source_runner, TrendsQueryRunner):
            trends_runner = cast(TrendsQueryRunner, self.source_runner)
            query = cast(InsightActorsQuery, self.query)
            return trends_runner.to_actors_query(
                time_frame=cast(Optional[str], query.day),  # Other runner accept day as int, but not this one
                series_index=query.series or 0,
                breakdown_value=query.breakdown,
                compare_value=query.compare,
                include_recordings=query.includeRecordings,
            )
        elif isinstance(self.source_runner, FunnelsQueryRunner):
            funnels_runner = cast(FunnelsQueryRunner, self.source_runner)
            funnels_runner.context.actorsQuery = cast(FunnelsActorsQuery, self.query)
            return funnels_runner.to_actors_query()
        elif isinstance(self.source_runner, FunnelCorrelationQueryRunner):
            funnel_correlation_runner = cast(FunnelCorrelationQueryRunner, self.source_runner)
            assert isinstance(self.query, FunnelCorrelationActorsQuery)
            funnel_correlation_runner.correlation_actors_query = self.query
            return funnel_correlation_runner.to_actors_query()
        elif isinstance(self.source_runner, RetentionQueryRunner):
            query = cast(InsightActorsQuery, self.query)
            retention_runner = cast(RetentionQueryRunner, self.source_runner)
            return retention_runner.to_actors_query(
                interval=query.interval,
                breakdown_values=query.breakdown,
            )
        elif isinstance(self.source_runner, PathsQueryRunner):
            paths_runner = cast(PathsQueryRunner, self.source_runner)
            return paths_runner.to_actors_query()
        elif isinstance(self.source_runner, StickinessQueryRunner):
            stickiness_runner = cast(StickinessQueryRunner, self.source_runner)
            stickiness_actors_query = cast(StickinessActorsQuery, self.query)
            return stickiness_runner.to_actors_query(
                interval_num=int(stickiness_actors_query.day) if stickiness_actors_query.day is not None else None,
                operator=getattr(stickiness_actors_query, "operator", None),
            )
        elif isinstance(self.source_runner, LifecycleQueryRunner):
            lifecycle_runner = cast(LifecycleQueryRunner, self.source_runner)
            query = cast(InsightActorsQuery, self.query)
            day = query.day
            status = query.status
            return lifecycle_runner.to_actors_query(day=str(day) if day else None, status=status)

        raise ValueError(f"Cannot convert source query of type {self.query.source.kind} to persons query")

    def to_actors_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return self.to_query()

    def to_events_query(self) -> ast.SelectQuery:
        if isinstance(self.source_runner, TrendsQueryRunner):
            trends_runner = cast(TrendsQueryRunner, self.source_runner)
            query = cast(InsightActorsQuery, self.query)
            return trends_runner.to_events_query(
                time_frame=cast(Optional[str], query.day),  # Other runner accept day as int, but not this one
                series_index=query.series or 0,
                breakdown_value=query.breakdown,
                compare_value=query.compare,
                include_recordings=query.includeRecordings,
            )

        if isinstance(self.source_runner, RetentionQueryRunner):
            retention_runner = cast(RetentionQueryRunner, self.source_runner)
            query = cast(InsightActorsQuery, self.query)
            if query.interval is None:
                raise ValueError("Interval is required for insight retention events query")

            return retention_runner.to_events_query(
                interval=query.interval,
                breakdown_value=query.breakdown,
            )

        raise ValueError(f"Cannot convert source query of type {self.query.source.kind} to events query")

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

    def _calculate(self) -> HogQLQueryResponse:
        settings = None

        # Funnel queries require the experimental analyzer to run correctly
        # Can remove once clickhouse moves to version 24.3 or above
        if isinstance(self.source_runner, FunnelsQueryRunner):
            settings = HogQLGlobalSettings(allow_experimental_analyzer=True)

        return execute_hogql_query(
            query_type="InsightActorsQuery",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            settings=settings,
        )
