from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.hogql_queries.web_analytics.query_builders.base import BaseStatsTableQueryBuilder
from posthog.hogql_queries.web_analytics.query_constants.stats_table_queries import FRUSTRATION_METRICS_INNER_QUERY


class FrustrationMetricsQueryBuilder(BaseStatsTableQueryBuilder):
    def build(self) -> ast.SelectQuery:
        with self.runner.timings.measure("frustration_metrics_query"):
            selects = [
                ast.Alias(alias="context.columns.breakdown_value", expr=self._processed_breakdown_value()),
                self._period_comparison_tuple("rage_clicks_count", "context.columns.rage_clicks", "sum"),
                self._period_comparison_tuple("dead_clicks_count", "context.columns.dead_clicks", "sum"),
                self._period_comparison_tuple("errors_count", "context.columns.errors", "sum"),
            ]

            query = ast.SelectQuery(
                select=selects,
                select_from=ast.JoinExpr(table=self._inner_query()),
                group_by=[ast.Field(chain=["context.columns.breakdown_value"])],
                order_by=self._frustration_metrics_order_by(),
            )

        return query

    def _inner_query(self) -> ast.SelectQuery:
        query = parse_select(
            FRUSTRATION_METRICS_INNER_QUERY,
            timings=self.runner.timings,
            placeholders={
                "breakdown_value": self._counts_breakdown_value(),
                "event_where": parse_expr(
                    "events.event IN ('$pageview', '$screen', '$rageclick', '$dead_click', '$exception')"
                ),
                "all_properties": self._all_properties(),
                "where_breakdown": self.where_breakdown(),
                "inside_periods": self._periods_expression(),
            },
        )

        assert isinstance(query, ast.SelectQuery)
        return query

    def _frustration_metrics_order_by(self) -> list[ast.OrderExpr]:
        return [
            ast.OrderExpr(expr=ast.Field(chain=["context.columns.errors"]), order="DESC"),
            ast.OrderExpr(expr=ast.Field(chain=["context.columns.rage_clicks"]), order="DESC"),
            ast.OrderExpr(expr=ast.Field(chain=["context.columns.dead_clicks"]), order="DESC"),
        ]
