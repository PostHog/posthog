from datetime import datetime, timedelta
from math import ceil
from typing import Any, Optional

from posthog.schema import (
    CachedFunnelsQueryResponse,
    Compare,
    FunnelsQuery,
    FunnelsQueryResponse,
    FunnelVizType,
    HogQLQueryModifiers,
    ResolvedDateRangeResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY, HogQLGlobalSettings, LimitContext
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings

from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.funnels.funnel_time_to_convert import FunnelTimeToConvert
from posthog.hogql_queries.insights.funnels.funnel_time_to_convert_udf import FunnelTimeToConvertUDF
from posthog.hogql_queries.insights.funnels.funnel_trends import FunnelTrends
from posthog.hogql_queries.insights.funnels.funnel_trends_udf import FunnelTrendsUDF
from posthog.hogql_queries.insights.funnels.utils import get_funnel_actor_class, get_funnel_order_class, use_udf
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.models import Team
from posthog.models.filters.mixins.utils import cached_property


class FunnelsQueryRunner(AnalyticsQueryRunner[FunnelsQueryResponse]):
    query: FunnelsQuery
    cached_response: CachedFunnelsQueryResponse
    context: FunnelQueryContext

    def __init__(
        self,
        query: FunnelsQuery | dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
        **kwargs,
    ):
        super().__init__(query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)

        self.context = FunnelQueryContext(
            query=self.query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context
        )
        self.kwargs = kwargs

    def _refresh_frequency(self):
        date_to = self.query_date_range.date_to()
        date_from = self.query_date_range.date_from()
        interval = self.query_date_range.interval_name

        delta_days: Optional[int] = None
        if date_from and date_to:
            delta = date_to - date_from
            delta_days = ceil(delta.total_seconds() / timedelta(days=1).total_seconds())

        refresh_frequency = BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL
        if interval == "hour" or (delta_days is not None and delta_days <= 7):
            refresh_frequency = REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL

        return refresh_frequency

    def to_query(self) -> ast.SelectQuery:
        if (self.context.funnelsFilter.funnelVizType == FunnelVizType.TRENDS and
            self.query.compareFilter is not None and
            self.query.compareFilter.compare):
            return ast.SelectSetQuery.create_from_queries(self.to_queries(), "UNION ALL")
        return self.funnel_class.get_query()

    def to_queries(self) -> list[ast.SelectQuery]:
        """Generate queries for current and comparison periods for funnel trends."""
        queries = []

        # Current period query
        current_query = self.funnel_class.get_query()
        queries.append(current_query)

        # Comparison period query
        if (self.query.compareFilter is not None and
            self.query.compareFilter.compare and
            self.context.funnelsFilter.funnelVizType == FunnelVizType.TRENDS):
            # Create a modified query with comparison date range
            comparison_query_obj = self.query.model_copy()
            if self.query.compareFilter.compare_to:
                comparison_query_obj.dateRange = self.query_previous_date_range.date_range()
            else:
                # Use previous period logic
                comparison_query_obj.dateRange = self.query_previous_date_range.date_range()

            # Create comparison context
            comparison_context = FunnelQueryContext(
                query=comparison_query_obj,
                team=self.team,
                timings=self.context.timings,
                modifiers=self.context.modifiers,
                limit_context=self.context.limit_context,
            )

            # Create comparison funnel class
            comparison_funnel_class = self.funnel_class.__class__(context=comparison_context)
            comparison_query = comparison_funnel_class.get_query()
            queries.append(comparison_query)

        return queries

    def to_actors_query(self) -> ast.SelectQuery:
        return self.funnel_actor_class.actor_query()

    def _calculate(self):
        # Handle comparison for funnel trends
        if (self.context.funnelsFilter.funnelVizType == FunnelVizType.TRENDS and
            self.query.compareFilter is not None and
            self.query.compareFilter.compare):
            queries = self.to_queries()
            timings = []

            # TODO: can we get this from execute_hogql_query as well?
            hogql = ""
            for i, query in enumerate(queries):
                if i > 0:
                    hogql += "\nUNION ALL\n"
                hogql += to_printed_hogql(query, self.team)

            # Execute queries and combine results
            all_results = []
            for i, query in enumerate(queries):
                response = execute_hogql_query(
                    query_type="FunnelsQuery",
                    query=query,
                    team=self.team,
                    timings=self.timings,
                    modifiers=self.modifiers,
                    limit_context=self.limit_context,
                    settings=HogQLGlobalSettings(
                        # Make sure funnel queries never OOM
                        max_bytes_before_external_group_by=MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY,
                        allow_experimental_analyzer=True,
                    ),
                )
                all_results.append(response.results)
                if response.timings is not None:
                    timings.extend(response.timings)

            # Combine results from current and comparison periods
            combined_results = []
            if len(all_results) >= 2:
                current_results = all_results[0]
                comparison_results = all_results[1]

                # Add compare label to results
                for result in current_results:
                    result_copy = list(result)
                    result_copy.append("current")
                    combined_results.append(tuple(result_copy))

                for result in comparison_results:
                    result_copy = list(result)
                    result_copy.append("previous")
                    combined_results.append(tuple(result_copy))
            else:
                combined_results = all_results[0] if all_results else []

            results = self.funnel_class._format_results(combined_results)
        else:
            query = self.to_query()
            timings = []

            # TODO: can we get this from execute_hogql_query as well?
            hogql = to_printed_hogql(query, self.team)

            response = execute_hogql_query(
                query_type="FunnelsQuery",
                query=query,
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
                settings=HogQLGlobalSettings(
                    # Make sure funnel queries never OOM
                    max_bytes_before_external_group_by=MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY,
                    allow_experimental_analyzer=True,
                ),
            )

            results = self.funnel_class._format_results(response.results)

            if response.timings is not None:
                timings.extend(response.timings)

        return FunnelsQueryResponse(
            isUdf=self._use_udf,
            results=results,
            timings=timings,
            hogql=hogql,
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
        )

    @cached_property
    def _use_udf(self):
        return use_udf(self.context.funnelsFilter, self.team)

    @cached_property
    def funnel_order_class(self):
        return get_funnel_order_class(self.context.funnelsFilter, use_udf=self._use_udf)(context=self.context)

    @cached_property
    def funnel_class(self):
        funnelVizType = self.context.funnelsFilter.funnelVizType

        if funnelVizType == FunnelVizType.TRENDS:
            if self._use_udf:
                return FunnelTrendsUDF(context=self.context, **self.kwargs)
            return FunnelTrends(context=self.context, **self.kwargs)
        elif funnelVizType == FunnelVizType.TIME_TO_CONVERT:
            if self._use_udf:
                return FunnelTimeToConvertUDF(context=self.context)
            return FunnelTimeToConvert(context=self.context)
        else:
            return self.funnel_order_class

    @cached_property
    def funnel_actor_class(self):
        return get_funnel_actor_class(self.context.funnelsFilter, self._use_udf)(context=self.context)

    @cached_property
    def query_date_range(self):
        if self.query.compareFilter is not None and self.query.compareFilter.compare and self.query.compareFilter.compare_to:
            return QueryCompareToDateRange(
                date_range=self.query.dateRange,
                team=self.team,
                interval=self.query.interval,
                now=datetime.now(),
                compare_to=self.query.compareFilter.compare_to,
            )
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=self.query.interval,
            now=datetime.now(),
        )

    @cached_property
    def query_previous_date_range(self):
        # We set exact_timerange here because we want to compare to the previous period that has happened up to this exact time
        if self.query.compareFilter is not None and isinstance(self.query.compareFilter.compare_to, str):
            return QueryCompareToDateRange(
                date_range=self.query.dateRange,
                team=self.team,
                interval=self.query.interval,
                now=datetime.now(),
                compare_to=self.query.compareFilter.compare_to,
            )
        return QueryPreviousPeriodDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=self.query.interval,
            now=datetime.now(),
        )
