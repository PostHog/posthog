from datetime import date, datetime, timedelta

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.transforms.eval_time_freeze import EvalTimeFreezeVisitor

SNAPSHOT_DATE = datetime(2025, 6, 15, 12, 0, 0)


class TestEvalTimeFreezeVisitor(BaseTest):
    @parameterized.expand(
        [
            ("now()", SNAPSHOT_DATE),
            ("NOW()", SNAPSHOT_DATE),
            ("current_timestamp()", SNAPSHOT_DATE),
            ("CURRENT_TIMESTAMP()", SNAPSHOT_DATE),
        ]
    )
    def test_datetime_generators_replaced_with_snapshot_datetime(self, expr_str: str, expected: datetime):
        node = parse_expr(expr_str)
        result = EvalTimeFreezeVisitor(SNAPSHOT_DATE).visit(node)
        assert isinstance(result, ast.Constant)
        assert result.value == expected

    @parameterized.expand(
        [
            ("today()", SNAPSHOT_DATE.date()),
            ("TODAY()", SNAPSHOT_DATE.date()),
        ]
    )
    def test_today_replaced_with_snapshot_date(self, expr_str: str, expected: date):
        node = parse_expr(expr_str)
        result = EvalTimeFreezeVisitor(SNAPSHOT_DATE).visit(node)
        assert isinstance(result, ast.Constant)
        assert result.value == expected

    @parameterized.expand(
        [
            ("yesterday()", SNAPSHOT_DATE.date() - timedelta(days=1)),
            ("YESTERDAY()", SNAPSHOT_DATE.date() - timedelta(days=1)),
        ]
    )
    def test_yesterday_replaced_with_snapshot_date_minus_one(self, expr_str: str, expected: date):
        node = parse_expr(expr_str)
        result = EvalTimeFreezeVisitor(SNAPSHOT_DATE).visit(node)
        assert isinstance(result, ast.Constant)
        assert result.value == expected

    def test_non_date_functions_unchanged(self):
        node = parse_expr("count()")
        result = EvalTimeFreezeVisitor(SNAPSHOT_DATE).visit(node)
        assert isinstance(result, ast.Call)
        assert result.name == "count"

    def test_nested_now_in_expression(self):
        node = parse_expr("dateDiff('day', now(), timestamp)")
        result = EvalTimeFreezeVisitor(SNAPSHOT_DATE).visit(node)
        assert isinstance(result, ast.Call)
        assert result.name == "dateDiff"
        assert isinstance(result.args[1], ast.Constant)
        assert result.args[1].value == SNAPSHOT_DATE
