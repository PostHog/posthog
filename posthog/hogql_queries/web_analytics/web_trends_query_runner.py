from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from posthog.schema import CachedWebTrendsQueryResponse, WebTrendsItem, WebTrendsQuery, WebTrendsQueryResponse

from posthog.hogql import ast

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.web_analytics.trends_pre_aggregated_query_builder import TrendsPreAggregatedQueryBuilder
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner
from posthog.models.filters.mixins.utils import cached_property


class WebTrendsQueryRunner(WebAnalyticsQueryRunner[WebTrendsQueryResponse]):
    query: WebTrendsQuery
    response: WebTrendsQueryResponse
    cached_response: CachedWebTrendsQueryResponse

    @property
    def use_v2_tables(self) -> bool:
        """Determine table version from team property, default to v2."""
        team_version = getattr(self.team, "web_analytics_pre_aggregated_tables_version", "v2")
        return team_version != "v1"

    @cached_property
    def query_date_range(self):
        # Override the parent's query_date_range to include interval support
        timezone_info = (
            ZoneInfo("UTC")
            if self.modifiers and not self.modifiers.convertToProjectTimezone
            else self.team.timezone_info
        )
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            timezone_info=timezone_info,
            interval=self.query.interval,
            now=datetime.now(timezone_info),
        )

    def _calculate(self) -> WebTrendsQueryResponse:
        query_builder = TrendsPreAggregatedQueryBuilder(self)

        if query_builder.can_use_preaggregated_tables():
            query = query_builder.get_query()
            response = self.run_query(query)
            results = [
                WebTrendsItem(
                    bucket=row[0],
                    metrics={metric.value: row[i + 1] for i, metric in enumerate(self.query.metrics or [])},
                )
                for row in response.results
            ]
            return WebTrendsQueryResponse(
                results=results,
                timings=response.timings,
                types=response.types,
                hogql=response.hogql,
                modifiers=self.modifiers,
                usedPreAggregatedTables=True,
            )
        else:
            # Fallback to regular events table query
            # This would be implemented later if needed
            raise NotImplementedError("Non-pre-aggregated web trends queries are not yet supported")

    def run_query(self, query: ast.SelectQuery) -> Any:
        from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

        hogql_runner = HogQLQueryRunner(
            query={"kind": "HogQLASTQuery", "query": query},
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )
        return hogql_runner.calculate()

    def to_query(self) -> ast.SelectQuery:
        query_builder = TrendsPreAggregatedQueryBuilder(self)
        return query_builder.get_query()
