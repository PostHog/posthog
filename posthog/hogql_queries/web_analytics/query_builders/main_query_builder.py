from typing import TYPE_CHECKING

from posthog.schema import WebStatsBreakdown

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.hogql_queries.web_analytics.query_builders.base import BaseStatsTableQueryBuilder
from posthog.hogql_queries.web_analytics.query_constants.stats_table_queries import MAIN_INNER_QUERY

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner


class MainQueryBuilder(BaseStatsTableQueryBuilder):
    def __init__(self, runner: "WebStatsTableQueryRunner"):
        super().__init__(runner)

    def build(self, breakdown: ast.Expr) -> ast.SelectQuery:
        with self.runner.timings.measure("stats_table_query"):
            selects = [
                ast.Alias(alias="context.columns.breakdown_value", expr=self._processed_breakdown_value()),
                self._period_comparison_tuple("filtered_person_id", "context.columns.visitors", "uniq"),
            ]

            if self.runner.query.conversionGoal is not None:
                selects.extend(self._conversion_selects())
            else:
                selects.extend(self._standard_selects())

            order_by = self._order_by(columns=[select.alias for select in selects])
            fill_fraction_expr = self._fill_fraction(order_by)
            if fill_fraction_expr:
                selects.append(fill_fraction_expr)

            query = ast.SelectQuery(
                select=selects,
                select_from=ast.JoinExpr(table=self._inner_query(breakdown)),
                group_by=[ast.Field(chain=["context.columns.breakdown_value"])],
                order_by=order_by,
            )

        return query

    def _conversion_selects(self) -> list[ast.Alias]:
        return [
            self._period_comparison_tuple("conversion_count", "context.columns.total_conversions", "sum"),
            self._period_comparison_tuple("conversion_person_id", "context.columns.unique_conversions", "uniq"),
            ast.Alias(
                alias="context.columns.conversion_rate",
                expr=ast.Tuple(
                    exprs=[
                        parse_expr(
                            "if(`context.columns.visitors`.1 = 0, NULL, `context.columns.unique_conversions`.1 / `context.columns.visitors`.1)"
                        ),
                        parse_expr(
                            "if(`context.columns.visitors`.2 = 0, NULL, `context.columns.unique_conversions`.2 / `context.columns.visitors`.2)"
                        ),
                    ]
                ),
            ),
        ]

    def _standard_selects(self) -> list[ast.Alias]:
        selects = [
            self._period_comparison_tuple("filtered_pageview_count", "context.columns.views", "sum"),
        ]

        if self._include_extra_aggregation_value():
            selects.append(self._extra_aggregation_value())

        if self.runner.query.includeBounceRate:
            selects.append(self._period_comparison_tuple("is_bounce", "context.columns.bounce_rate", "avg"))

        return selects

    def _include_extra_aggregation_value(self) -> bool:
        return self.runner.query.breakdownBy == WebStatsBreakdown.LANGUAGE

    def _extra_aggregation_value(self) -> ast.Alias:
        match self.runner.query.breakdownBy:
            case WebStatsBreakdown.LANGUAGE:
                return parse_expr(
                    "arrayElement(topK(1)(arrayElement(splitByChar('-', assumeNotNull(breakdown_value), 2), 2)), 1) AS `context.columns.aggregation_value`"
                )
            case _:
                raise NotImplementedError("Aggregation value not exists")

    def _inner_query(self, breakdown: ast.Expr) -> ast.SelectQuery:
        query = parse_select(
            MAIN_INNER_QUERY,
            timings=self.runner.timings,
            placeholders={
                "breakdown_value": breakdown,
                "event_where": self.runner.event_type_expr,
                "all_properties": self._all_properties(),
                "where_breakdown": self.where_breakdown(),
                "inside_periods": self._periods_expression(),
            },
        )

        assert isinstance(query, ast.SelectQuery)

        if self.runner.conversion_count_expr and self.runner.conversion_person_id_expr:
            query.select.append(ast.Alias(alias="conversion_count", expr=self.runner.conversion_count_expr))
            query.select.append(ast.Alias(alias="conversion_person_id", expr=self.runner.conversion_person_id_expr))

        return query
