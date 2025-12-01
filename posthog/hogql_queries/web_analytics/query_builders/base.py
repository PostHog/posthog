from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Literal, Optional, cast

from posthog.schema import WebAnalyticsOrderByDirection, WebAnalyticsOrderByFields, WebStatsBreakdown

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr

from posthog.hogql_queries.web_analytics.query_builders.breakdown import BREAKDOWN_CONFIGS

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner


class BaseStatsTableQueryBuilder(ABC):
    """Base class for all stats table query builders."""

    def __init__(self, runner: "WebStatsTableQueryRunner"):
        self.runner = runner

    @abstractmethod
    def build(self) -> ast.SelectQuery:
        pass

    def _all_properties(self) -> ast.Expr:
        properties = self.runner.query.properties + self.runner._test_account_filters
        return property_to_expr(properties, team=self.runner.team)

    def _counts_breakdown_value(self) -> ast.Expr:
        return self.runner._counts_breakdown_value()

    def _periods_expression(self) -> ast.Expr:
        return self.runner._periods_expression()

    def where_breakdown(self):
        config = BREAKDOWN_CONFIGS.get(self.runner.query.breakdownBy)

        if config is None:
            raise NotImplementedError(f"Breakdown {self.query.breakdownBy} not implemented")

        return config.build_where_expr()

    def _order_by(self, columns: list[str]) -> list[ast.OrderExpr] | None:
        column = None
        direction: Literal["ASC", "DESC"] = "DESC"
        if self.runner.query.orderBy:
            field = cast(WebAnalyticsOrderByFields, self.runner.query.orderBy[0])
            direction = cast(WebAnalyticsOrderByDirection, self.runner.query.orderBy[1]).value

            if field == WebAnalyticsOrderByFields.VISITORS:
                column = "context.columns.visitors"
            elif field == WebAnalyticsOrderByFields.VIEWS:
                column = "context.columns.views"
            elif field == WebAnalyticsOrderByFields.CLICKS:
                column = "context.columns.clicks"
            elif field == WebAnalyticsOrderByFields.BOUNCE_RATE:
                column = "context.columns.bounce_rate"
            elif field == WebAnalyticsOrderByFields.AVERAGE_SCROLL_PERCENTAGE:
                column = "context.columns.average_scroll_percentage"
            elif field == WebAnalyticsOrderByFields.SCROLL_GT80_PERCENTAGE:
                column = "context.columns.scroll_gt80_percentage"
            elif field == WebAnalyticsOrderByFields.TOTAL_CONVERSIONS:
                column = "context.columns.total_conversions"
            elif field == WebAnalyticsOrderByFields.UNIQUE_CONVERSIONS:
                column = "context.columns.unique_conversions"
            elif field == WebAnalyticsOrderByFields.CONVERSION_RATE:
                column = "context.columns.conversion_rate"
            elif field == WebAnalyticsOrderByFields.RAGE_CLICKS:
                column = "context.columns.rage_clicks"
            elif field == WebAnalyticsOrderByFields.DEAD_CLICKS:
                column = "context.columns.dead_clicks"
            elif field == WebAnalyticsOrderByFields.ERRORS:
                column = "context.columns.errors"

        def f(c: str) -> Optional[ast.OrderExpr]:
            return ast.OrderExpr(expr=ast.Field(chain=[c]), order=direction) if column != c and c in columns else None

        return [
            expr
            for expr in [
                (
                    ast.OrderExpr(expr=ast.Field(chain=[column]), order=direction)
                    if column is not None and column in columns
                    else None
                ),
                f("context.columns.unique_conversions"),
                f("context.columns.total_conversions"),
                f("context.columns.visitors"),
                f("context.columns.views"),
                ast.OrderExpr(expr=ast.Field(chain=["context.columns.breakdown_value"]), order="ASC"),
            ]
            if expr is not None
        ]

    def _fill_fraction(self, order: Optional[list[ast.OrderExpr]]) -> Optional[ast.Alias]:
        col_name = (
            order[0].expr.chain[0]
            if order and isinstance(order[0].expr, ast.Field) and len(order[0].expr.chain) == 1
            else None
        )

        if col_name:
            if col_name in [
                "context.columns.visitors",
                "context.columns.views",
                "context.columns.clicks",
                "context.columns.total_conversions",
                "context.columns.unique_conversions",
                "context.columns.rage_clicks",
                "context.columns.dead_clicks",
                "context.columns.errors",
            ]:
                return ast.Alias(
                    alias="context.columns.ui_fill_fraction",
                    expr=parse_expr(
                        "{col}.1 / sum({col}.1) OVER ()",
                        placeholders={"col": ast.Field(chain=[col_name])},
                    ),
                )
            if col_name in [
                "context.columns.bounce_rate",
                "context.columns.average_scroll_percentage",
                "context.columns.scroll_gt80_percentage",
                "context.columns.conversion_rate",
            ]:
                return ast.Alias(
                    alias="context.columns.ui_fill_fraction",
                    expr=parse_expr(
                        "{col}.1",
                        placeholders={"col": ast.Field(chain=[col_name])},
                    ),
                )
        return ast.Alias(
            alias="context.columns.ui_fill_fraction",
            expr=parse_expr(""" "context.columns.visitors".1 / sum("context.columns.visitors".1) OVER ()"""),
        )

    def _processed_breakdown_value(self) -> ast.Expr:
        if self.runner.query.breakdownBy == WebStatsBreakdown.LANGUAGE:
            return parse_expr("arrayElement(splitByChar('-', assumeNotNull(breakdown_value), 2), 1)")
        return ast.Field(chain=["breakdown_value"])

    def _period_comparison_tuple(self, column: str, alias: str, function_name: str) -> ast.Alias:
        return ast.Alias(
            alias=alias,
            expr=ast.Tuple(
                exprs=[
                    self._current_period_aggregate(function_name, column),
                    self._previous_period_aggregate(function_name, column),
                ]
            ),
        )

    def _current_period_aggregate(self, function_name: str, column_name: str) -> ast.Expr:
        if not self.runner.query_compare_to_date_range:
            return ast.Call(name=function_name, args=[ast.Field(chain=[column_name])])

        return self.runner.period_aggregate(
            function_name,
            column_name,
            self.runner.query_date_range.date_from_as_hogql(),
            self.runner.query_date_range.date_to_as_hogql(),
        )

    def _previous_period_aggregate(self, function_name: str, column_name: str) -> ast.Expr:
        if not self.runner.query_compare_to_date_range:
            return ast.Constant(value=None)

        return self.runner.period_aggregate(
            function_name,
            column_name,
            self.runner.query_compare_to_date_range.date_from_as_hogql(),
            self.runner.query_compare_to_date_range.date_to_as_hogql(),
        )
