from posthog.hogql import ast
from posthog.schema import ChartDisplayType


class TrendsDisplay:
    display_type: ChartDisplayType

    def __init__(self, display_type: ChartDisplayType) -> None:
        self.display_type = display_type

    def should_aggregate_values(self) -> bool:
        return (
            self.display_type == ChartDisplayType.BoldNumber
            or self.display_type == ChartDisplayType.ActionsPie
            or self.display_type == ChartDisplayType.ActionsBarValue
            or self.display_type == ChartDisplayType.WorldMap
        )

    def wrap_inner_query(self, inner_query: ast.SelectQuery, breakdown_enabled: bool) -> ast.SelectQuery:
        if self.display_type == ChartDisplayType.ActionsLineGraphCumulative:
            return self._get_cumulative_query(inner_query, breakdown_enabled)

        return inner_query

    def should_wrap_inner_query(self) -> bool:
        return self.display_type == ChartDisplayType.ActionsLineGraphCumulative

    def modify_outer_query(self, outer_query: ast.SelectQuery, inner_query: ast.SelectQuery) -> ast.SelectQuery:
        if (
            self.display_type == ChartDisplayType.BoldNumber
            or self.display_type == ChartDisplayType.ActionsPie
            or self.display_type == ChartDisplayType.WorldMap
        ):
            return ast.SelectQuery(
                select=[
                    ast.Alias(
                        alias="total",
                        expr=ast.Call(name="sum", args=[ast.Field(chain=["count"])]),
                    )
                ],
                select_from=ast.JoinExpr(table=inner_query),
            )

        return outer_query

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
                        args=[ast.Field(chain=["count"])],
                        over_expr=window_expr,
                    ),
                ),
            ],
            select_from=ast.JoinExpr(table=inner_query),
        )
