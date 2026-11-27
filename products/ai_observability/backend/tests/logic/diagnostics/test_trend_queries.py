from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from products.ai_observability.backend.logic.diagnostics.trend_queries import (
    failing_expression,
    failure_rate_expression,
    trend_expression,
)
from products.ai_observability.backend.logic.diagnostics.trends import Trend


class TestTrendExpressions(ClickhouseTestMixin, BaseTest):
    def _select(self, expr: ast.Expr) -> Any:
        response = execute_hogql_query(query=ast.SelectQuery(select=[expr]), team=self.team)
        assert response.results is not None
        [(value,)] = response.results
        return value

    @parameterized.expand(
        [
            ("rise_of_exactly_the_minimum_percent", 12, 10, Trend.INCREASING),
            ("rise_under_the_minimum_percent", 11, 10, Trend.STEADY),
            ("from_zero_at_the_minimum_occurrences", 10, 0, Trend.INCREASING),
            ("from_zero_under_the_minimum_occurrences", 9, 0, Trend.STEADY),
            ("fall_of_exactly_the_minimum_percent", 8, 10, Trend.DECREASING),
            ("fall_from_under_the_minimum_occurrences", 7, 9, Trend.STEADY),
            ("no_previous_window", 5, None, Trend.STEADY),
        ]
    )
    def test_trend(self, _name: str, current: int, previous: int | None, expected: Trend) -> None:
        expr = trend_expression(
            ast.Constant(value=current), ast.Constant(value=previous) if previous is not None else None
        )

        assert Trend(self._select(expr)) == expected

    def test_a_group_absent_from_the_previous_window_rises_from_zero(self) -> None:
        expr = trend_expression(ast.Constant(value=10), ast.Constant(value=None))

        assert Trend(self._select(expr)) == Trend.INCREASING

    @parameterized.expand(
        [
            ("at_the_minimum_rate_and_results", 20, 1, True),
            ("under_the_minimum_results", 19, 5, False),
            ("under_the_minimum_rate", 100, 4, False),
            ("no_captured_result", 0, 0, False),
        ]
    )
    def test_failing(self, _name: str, results: int, failures: int, expected: bool) -> None:
        rate = failure_rate_expression(ast.Constant(value=results), ast.Constant(value=failures))
        expr = failing_expression(ast.Constant(value=results), rate)

        assert bool(self._select(expr)) is expected

    @parameterized.expand([("some_results", 40, 3, 0.075), ("no_results", 0, 0, None)])
    def test_failure_rate(self, _name: str, results: int, failures: int, expected: float | None) -> None:
        expr = failure_rate_expression(ast.Constant(value=results), ast.Constant(value=failures))

        assert self._select(expr) == expected
