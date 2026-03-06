import unittest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.helpers.timestamp_visitor import (
    IsEndOfDayConstantVisitor,
    IsEndOfHourConstantVisitor,
    IsSimpleTimestampFieldExpressionVisitor,
    IsStartOfDayConstantVisitor,
    IsStartOfHourConstantVisitor,
    IsTimeOrIntervalConstantVisitor,
    is_end_of_day_constant,
    is_end_of_hour_constant,
    is_simple_timestamp_field_expression,
    is_start_of_day_constant,
    is_start_of_hour_constant,
    is_time_or_interval_constant,
)


def _make_select_set_query() -> ast.SelectSetQuery:
    return ast.SelectSetQuery(
        initial_select_query=ast.SelectQuery(select=[ast.Constant(value=1)]),
        subsequent_select_queries=[
            ast.SelectSetNode(
                select_query=ast.SelectQuery(select=[ast.Constant(value=2)]),
                set_operator="UNION ALL",
            )
        ],
    )


def _make_hogql_context() -> HogQLContext:
    return HogQLContext(team_id=1)


class TestTimestampVisitorSelectSetQuery(unittest.TestCase):
    """Regression tests for visit_select_set_query methods (PR #49867)."""

    @parameterized.expand(
        [
            (
                "IsSimpleTimestampFieldExpressionVisitor",
                lambda: IsSimpleTimestampFieldExpressionVisitor(_make_hogql_context(), None),
            ),
            ("IsTimeOrIntervalConstantVisitor", lambda: IsTimeOrIntervalConstantVisitor(None)),
            ("IsStartOfDayConstantVisitor", lambda: IsStartOfDayConstantVisitor(None)),
            ("IsStartOfHourConstantVisitor", lambda: IsStartOfHourConstantVisitor(None)),
            ("IsEndOfDayConstantVisitor", lambda: IsEndOfDayConstantVisitor(None)),
            ("IsEndOfHourConstantVisitor", lambda: IsEndOfHourConstantVisitor(None)),
        ]
    )
    def test_select_set_query_returns_false(self, _name: str, make_visitor) -> None:
        node = _make_select_set_query()
        result = make_visitor().visit(node)
        self.assertFalse(result)

    def test_select_set_query_does_not_raise_not_implemented(self) -> None:
        node = _make_select_set_query()
        visitors = [
            IsSimpleTimestampFieldExpressionVisitor(_make_hogql_context(), None),
            IsTimeOrIntervalConstantVisitor(None),
            IsStartOfDayConstantVisitor(None),
            IsStartOfHourConstantVisitor(None),
            IsEndOfDayConstantVisitor(None),
            IsEndOfHourConstantVisitor(None),
        ]
        for visitor in visitors:
            # Should not raise NotImplementedError
            visitor.visit(node)

    @parameterized.expand(
        [
            (
                "is_simple_timestamp_field_expression",
                lambda n: is_simple_timestamp_field_expression(n, _make_hogql_context()),
            ),
            ("is_time_or_interval_constant", lambda n: is_time_or_interval_constant(n)),
            ("is_start_of_day_constant", lambda n: is_start_of_day_constant(n)),
            ("is_start_of_hour_constant", lambda n: is_start_of_hour_constant(n)),
            ("is_end_of_day_constant", lambda n: is_end_of_day_constant(n)),
            ("is_end_of_hour_constant", lambda n: is_end_of_hour_constant(n)),
        ]
    )
    def test_helper_functions_handle_select_set_query(self, _name: str, helper_fn) -> None:
        node = _make_select_set_query()
        self.assertFalse(helper_fn(node))


class TestIsTimeOrIntervalConstant(unittest.TestCase):
    def test_constant_returns_true(self) -> None:
        self.assertTrue(is_time_or_interval_constant(ast.Constant(value="2024-01-01")))

    def test_constant_with_tombstone_returns_false(self) -> None:
        self.assertFalse(is_time_or_interval_constant(ast.Constant(value="tombstone"), tombstone_string="tombstone"))

    def test_field_returns_false(self) -> None:
        self.assertFalse(is_time_or_interval_constant(ast.Field(chain=["timestamp"])))

    def test_select_query_returns_false(self) -> None:
        self.assertFalse(is_time_or_interval_constant(ast.SelectQuery(select=[ast.Constant(value=1)])))

    @parameterized.expand(
        [
            ("today",),
            ("now",),
            ("now64",),
            ("yesterday",),
        ]
    )
    def test_time_functions_return_true(self, fn_name: str) -> None:
        self.assertTrue(is_time_or_interval_constant(ast.Call(name=fn_name, args=[])))

    @parameterized.expand(
        [
            ("toDateTime",),
            ("toDateTime64",),
            ("toTimeZone",),
            ("assumeNotNull",),
            ("parseDateTime64BestEffortOrNull",),
        ]
    )
    def test_wrapping_functions_delegate_to_first_arg(self, fn_name: str) -> None:
        self.assertTrue(is_time_or_interval_constant(ast.Call(name=fn_name, args=[ast.Constant(value="2024-01-01")])))
        self.assertFalse(is_time_or_interval_constant(ast.Call(name=fn_name, args=[ast.Field(chain=["x"])])))

    def test_toInterval_prefix_delegates(self) -> None:
        self.assertTrue(is_time_or_interval_constant(ast.Call(name="toIntervalDay", args=[ast.Constant(value=1)])))

    def test_toStartOf_prefix_delegates(self) -> None:
        self.assertTrue(
            is_time_or_interval_constant(ast.Call(name="toStartOfDay", args=[ast.Constant(value="2024-01-01")]))
        )

    def test_arithmetic_both_constants_true(self) -> None:
        self.assertTrue(
            is_time_or_interval_constant(
                ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Add,
                    left=ast.Constant(value="2024-01-01"),
                    right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=1)]),
                )
            )
        )

    def test_arithmetic_with_field_false(self) -> None:
        self.assertFalse(
            is_time_or_interval_constant(
                ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Add,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=1),
                )
            )
        )

    def test_minus_call_with_constants_true(self) -> None:
        self.assertTrue(
            is_time_or_interval_constant(
                ast.Call(name="minus", args=[ast.Constant(value="2024-01-01"), ast.Constant(value=1)])
            )
        )

    def test_and_returns_false(self) -> None:
        self.assertFalse(is_time_or_interval_constant(ast.And(exprs=[ast.Constant(value=True)])))

    def test_or_returns_false(self) -> None:
        self.assertFalse(is_time_or_interval_constant(ast.Or(exprs=[ast.Constant(value=True)])))

    def test_not_returns_false(self) -> None:
        self.assertFalse(is_time_or_interval_constant(ast.Not(expr=ast.Constant(value=True))))

    def test_alias_delegates_to_expr(self) -> None:
        self.assertTrue(is_time_or_interval_constant(ast.Alias(alias="a", expr=ast.Constant(value="2024-01-01"))))
        self.assertFalse(is_time_or_interval_constant(ast.Alias(alias="a", expr=ast.Field(chain=["x"]))))

    def test_tuple_all_constants_true(self) -> None:
        self.assertTrue(
            is_time_or_interval_constant(ast.Tuple(exprs=[ast.Constant(value="a"), ast.Constant(value="b")]))
        )

    def test_tuple_with_field_false(self) -> None:
        self.assertFalse(
            is_time_or_interval_constant(ast.Tuple(exprs=[ast.Constant(value="a"), ast.Field(chain=["x"])]))
        )

    def test_array_all_constants_true(self) -> None:
        self.assertTrue(
            is_time_or_interval_constant(ast.Array(exprs=[ast.Constant(value="a"), ast.Constant(value="b")]))
        )

    def test_compare_both_constants_true(self) -> None:
        self.assertTrue(
            is_time_or_interval_constant(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Constant(value="a"),
                    right=ast.Constant(value="b"),
                )
            )
        )

    def test_between_returns_false(self) -> None:
        self.assertFalse(
            is_time_or_interval_constant(
                ast.BetweenExpr(
                    expr=ast.Constant(value=1),
                    low=ast.Constant(value=0),
                    high=ast.Constant(value=2),
                )
            )
        )

    def test_unknown_call_returns_false(self) -> None:
        self.assertFalse(is_time_or_interval_constant(ast.Call(name="unknownFunction", args=[ast.Constant(value=1)])))


class TestIsStartOfDayConstant(unittest.TestCase):
    def test_start_of_day_string_true(self) -> None:
        self.assertTrue(is_start_of_day_constant(ast.Constant(value="2024-01-15T00:00:00")))

    def test_non_start_of_day_string_false(self) -> None:
        self.assertFalse(is_start_of_day_constant(ast.Constant(value="2024-01-15T12:30:00")))

    def test_non_string_constant_false(self) -> None:
        self.assertFalse(is_start_of_day_constant(ast.Constant(value=42)))

    def test_invalid_date_string_false(self) -> None:
        self.assertFalse(is_start_of_day_constant(ast.Constant(value="not-a-date")))

    def test_today_function_true(self) -> None:
        self.assertTrue(is_start_of_day_constant(ast.Call(name="today", args=[])))

    def test_yesterday_function_true(self) -> None:
        self.assertTrue(is_start_of_day_constant(ast.Call(name="yesterday", args=[])))

    def test_toStartOfDay_with_constant_true(self) -> None:
        self.assertTrue(
            is_start_of_day_constant(ast.Call(name="toStartOfDay", args=[ast.Constant(value="2024-01-01")]))
        )

    def test_toStartOfWeek_with_constant_true(self) -> None:
        self.assertTrue(
            is_start_of_day_constant(ast.Call(name="toStartOfWeek", args=[ast.Constant(value="2024-01-01")]))
        )

    def test_field_returns_false(self) -> None:
        self.assertFalse(is_start_of_day_constant(ast.Field(chain=["timestamp"])))

    def test_select_query_returns_false(self) -> None:
        self.assertFalse(is_start_of_day_constant(ast.SelectQuery(select=[ast.Constant(value=1)])))

    def test_tombstone_returns_false(self) -> None:
        self.assertFalse(is_start_of_day_constant(ast.Constant(value="tombstone"), tombstone_string="tombstone"))

    def test_parseDateTime64BestEffortOrNull_delegates(self) -> None:
        self.assertTrue(
            is_start_of_day_constant(
                ast.Call(name="parseDateTime64BestEffortOrNull", args=[ast.Constant(value="2024-01-15T00:00:00")])
            )
        )
        self.assertFalse(
            is_start_of_day_constant(
                ast.Call(name="parseDateTime64BestEffortOrNull", args=[ast.Constant(value="2024-01-15T12:30:00")])
            )
        )


class TestIsStartOfHourConstant(unittest.TestCase):
    def test_start_of_hour_string_true(self) -> None:
        self.assertTrue(is_start_of_hour_constant(ast.Constant(value="2024-01-15T14:00:00")))

    def test_non_start_of_hour_string_false(self) -> None:
        self.assertFalse(is_start_of_hour_constant(ast.Constant(value="2024-01-15T14:30:00")))

    def test_toStartOfHour_with_constant_true(self) -> None:
        self.assertTrue(
            is_start_of_hour_constant(ast.Call(name="toStartOfHour", args=[ast.Constant(value="2024-01-01")]))
        )

    def test_start_of_day_also_start_of_hour(self) -> None:
        self.assertTrue(is_start_of_hour_constant(ast.Constant(value="2024-01-15T00:00:00")))


class TestIsEndOfDayConstant(unittest.TestCase):
    def test_end_of_day_string_true(self) -> None:
        self.assertTrue(is_end_of_day_constant(ast.Constant(value="2024-01-15T23:59:59")))

    def test_non_end_of_day_string_false(self) -> None:
        self.assertFalse(is_end_of_day_constant(ast.Constant(value="2024-01-15T12:00:00")))

    def test_non_string_constant_false(self) -> None:
        self.assertFalse(is_end_of_day_constant(ast.Constant(value=42)))

    def test_field_returns_false(self) -> None:
        self.assertFalse(is_end_of_day_constant(ast.Field(chain=["timestamp"])))

    def test_select_query_returns_false(self) -> None:
        self.assertFalse(is_end_of_day_constant(ast.SelectQuery(select=[ast.Constant(value=1)])))

    def test_tombstone_returns_false(self) -> None:
        self.assertFalse(is_end_of_day_constant(ast.Constant(value="tombstone"), tombstone_string="tombstone"))

    def test_parseDateTime64BestEffortOrNull_delegates(self) -> None:
        self.assertTrue(
            is_end_of_day_constant(
                ast.Call(name="parseDateTime64BestEffortOrNull", args=[ast.Constant(value="2024-01-15T23:59:59")])
            )
        )


class TestIsEndOfHourConstant(unittest.TestCase):
    def test_end_of_hour_string_true(self) -> None:
        self.assertTrue(is_end_of_hour_constant(ast.Constant(value="2024-01-15T14:59:59")))

    def test_non_end_of_hour_string_false(self) -> None:
        self.assertFalse(is_end_of_hour_constant(ast.Constant(value="2024-01-15T14:30:00")))

    def test_end_of_day_also_end_of_hour(self) -> None:
        self.assertTrue(is_end_of_hour_constant(ast.Constant(value="2024-01-15T23:59:59")))


class TestIsSimpleTimestampFieldExpression(unittest.TestCase):
    def test_constant_returns_false(self) -> None:
        ctx = _make_hogql_context()
        self.assertFalse(is_simple_timestamp_field_expression(ast.Constant(value="2024-01-01"), ctx))

    def test_select_query_returns_false(self) -> None:
        ctx = _make_hogql_context()
        self.assertFalse(is_simple_timestamp_field_expression(ast.SelectQuery(select=[ast.Constant(value=1)]), ctx))

    def test_timestamp_field_without_type_returns_true(self) -> None:
        ctx = _make_hogql_context()
        self.assertTrue(is_simple_timestamp_field_expression(ast.Field(chain=["timestamp"]), ctx))

    @parameterized.expand(
        [
            ("$start_timestamp",),
            ("$end_timestamp",),
            ("min_timestamp",),
            ("min_first_timestamp",),
        ]
    )
    def test_known_timestamp_fields_return_true(self, field_name: str) -> None:
        ctx = _make_hogql_context()
        self.assertTrue(is_simple_timestamp_field_expression(ast.Field(chain=[field_name]), ctx))

    def test_non_timestamp_field_without_type_returns_false(self) -> None:
        ctx = _make_hogql_context()
        self.assertFalse(is_simple_timestamp_field_expression(ast.Field(chain=["event"]), ctx))

    def test_compare_operation_returns_false(self) -> None:
        ctx = _make_hogql_context()
        self.assertFalse(
            is_simple_timestamp_field_expression(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value="2024-01-01"),
                ),
                ctx,
            )
        )

    def test_and_returns_false(self) -> None:
        ctx = _make_hogql_context()
        self.assertFalse(
            is_simple_timestamp_field_expression(
                ast.And(exprs=[ast.Constant(value=True), ast.Constant(value=True)]),
                ctx,
            )
        )

    def test_or_returns_false(self) -> None:
        ctx = _make_hogql_context()
        self.assertFalse(
            is_simple_timestamp_field_expression(
                ast.Or(exprs=[ast.Constant(value=True)]),
                ctx,
            )
        )

    def test_not_returns_false(self) -> None:
        ctx = _make_hogql_context()
        self.assertFalse(is_simple_timestamp_field_expression(ast.Not(expr=ast.Constant(value=True)), ctx))

    def test_between_returns_false(self) -> None:
        ctx = _make_hogql_context()
        self.assertFalse(
            is_simple_timestamp_field_expression(
                ast.BetweenExpr(
                    expr=ast.Constant(value=1),
                    low=ast.Constant(value=0),
                    high=ast.Constant(value=2),
                ),
                ctx,
            )
        )

    @parameterized.expand(
        [
            ("toDateTime",),
            ("toTimeZone",),
            ("assumeNotNull",),
            ("toStartOfDay",),
            ("toStartOfWeek",),
            ("toStartOfMonth",),
        ]
    )
    def test_wrapping_call_delegates_to_first_arg(self, fn_name: str) -> None:
        ctx = _make_hogql_context()
        self.assertTrue(
            is_simple_timestamp_field_expression(
                ast.Call(name=fn_name, args=[ast.Field(chain=["timestamp"])]),
                ctx,
            )
        )
        self.assertFalse(
            is_simple_timestamp_field_expression(
                ast.Call(name=fn_name, args=[ast.Field(chain=["event"])]),
                ctx,
            )
        )

    def test_minus_call_delegates_like_arithmetic(self) -> None:
        ctx = _make_hogql_context()
        self.assertTrue(
            is_simple_timestamp_field_expression(
                ast.Call(
                    name="minus",
                    args=[ast.Field(chain=["timestamp"]), ast.Call(name="toIntervalDay", args=[ast.Constant(value=1)])],
                ),
                ctx,
            )
        )

    def test_add_call_delegates_like_arithmetic(self) -> None:
        ctx = _make_hogql_context()
        self.assertTrue(
            is_simple_timestamp_field_expression(
                ast.Call(
                    name="add",
                    args=[ast.Field(chain=["timestamp"]), ast.Call(name="toIntervalDay", args=[ast.Constant(value=1)])],
                ),
                ctx,
            )
        )

    def test_unknown_call_returns_false(self) -> None:
        ctx = _make_hogql_context()
        self.assertFalse(
            is_simple_timestamp_field_expression(
                ast.Call(name="unknownFunction", args=[ast.Field(chain=["timestamp"])]),
                ctx,
            )
        )

    def test_arithmetic_timestamp_plus_interval(self) -> None:
        ctx = _make_hogql_context()
        self.assertTrue(
            is_simple_timestamp_field_expression(
                ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Add,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=1)]),
                ),
                ctx,
            )
        )

    def test_arithmetic_interval_plus_timestamp(self) -> None:
        ctx = _make_hogql_context()
        self.assertTrue(
            is_simple_timestamp_field_expression(
                ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Add,
                    left=ast.Call(name="toIntervalDay", args=[ast.Constant(value=1)]),
                    right=ast.Field(chain=["timestamp"]),
                ),
                ctx,
            )
        )

    def test_arithmetic_two_fields_returns_false(self) -> None:
        ctx = _make_hogql_context()
        self.assertFalse(
            is_simple_timestamp_field_expression(
                ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Add,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Field(chain=["timestamp"]),
                ),
                ctx,
            )
        )

    def test_tuple_all_timestamp_fields(self) -> None:
        ctx = _make_hogql_context()
        self.assertTrue(
            is_simple_timestamp_field_expression(
                ast.Tuple(exprs=[ast.Field(chain=["timestamp"]), ast.Field(chain=["timestamp"])]),
                ctx,
            )
        )

    def test_tuple_with_non_timestamp_field_false(self) -> None:
        ctx = _make_hogql_context()
        self.assertFalse(
            is_simple_timestamp_field_expression(
                ast.Tuple(exprs=[ast.Field(chain=["timestamp"]), ast.Field(chain=["event"])]),
                ctx,
            )
        )

    def test_array_all_timestamp_fields(self) -> None:
        ctx = _make_hogql_context()
        self.assertTrue(
            is_simple_timestamp_field_expression(
                ast.Array(exprs=[ast.Field(chain=["timestamp"]), ast.Field(chain=["timestamp"])]),
                ctx,
            )
        )
