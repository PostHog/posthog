from posthog.schema import ChartDisplayType

from posthog.hogql import ast
from posthog.hogql.parser import parse_select


class TrendsDisplay:
    display_type: ChartDisplayType

    def __init__(self, display_type: ChartDisplayType | None) -> None:
        if display_type:
            self.display_type = display_type
        else:
            self.display_type = ChartDisplayType.ACTIONS_LINE_GRAPH

    # No time range
    def is_total_value(self) -> bool:
        return (
            self.display_type == ChartDisplayType.BOLD_NUMBER
            or self.display_type == ChartDisplayType.ACTIONS_PIE
            or self.display_type == ChartDisplayType.ACTIONS_BAR_VALUE
            or self.display_type == ChartDisplayType.WORLD_MAP
            or self.display_type == ChartDisplayType.CALENDAR_HEATMAP
            or self.display_type == ChartDisplayType.ACTIONS_TABLE
        )

    def wrap_inner_query(self, inner_query: ast.SelectQuery, breakdown_enabled: bool) -> ast.SelectQuery:
        if self.display_type == ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE:
            return self._get_cumulative_query(inner_query, breakdown_enabled)

        return inner_query

    def should_wrap_inner_query(self) -> bool:
        return self.display_type == ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE

    def _build_aggregate_dates(self, dates_queries: ast.SelectSetQuery) -> ast.Expr:
        return parse_select(
            """
            SELECT day_start
            FROM (
                SELECT 1 as group_key, groupArray(day_start) as day_start
                FROM (
                    SELECT day_start
                    FROM {dates_queries}
                    ORDER BY day_start
                )
                GROUP BY group_key
            )
            """,
            placeholders={"dates_queries": dates_queries},
        )

    def modify_outer_query(
        self, outer_query: ast.SelectQuery, inner_query: ast.SelectQuery, dates_queries: ast.SelectSetQuery
    ) -> ast.SelectQuery:
        if not self.is_total_value():
            return outer_query

        return ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="total",
                    expr=ast.Call(name="sum", args=[ast.Field(chain=["count"])]),
                ),
                ast.Alias(alias="date", expr=self._build_aggregate_dates(dates_queries)),
            ],
            select_from=ast.JoinExpr(table=inner_query),
        )

    def _get_cumulative_query(self, inner_query: ast.SelectQuery, breakdown_enabled: bool) -> ast.SelectQuery:
        if breakdown_enabled:
            window_expr = ast.WindowExpr(
                order_by=[ast.OrderExpr(expr=ast.Field(chain=["day_start"]), order="ASC")],
                partition_by=[ast.Field(chain=["breakdown_value"])],
            )
        else:
            window_expr = ast.WindowExpr(order_by=[ast.OrderExpr(expr=ast.Field(chain=["day_start"]), order="ASC")])

        return ast.SelectQuery(
            select=[
                ast.Field(chain=["day_start"]),
                ast.Alias(
                    alias="count",
                    expr=ast.WindowFunction(
                        name="sum",
                        exprs=[ast.Field(chain=["count"])],
                        over_expr=window_expr,
                    ),
                ),
            ],
            select_from=ast.JoinExpr(table=inner_query),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["day_start"]), order="ASC")],
        )
