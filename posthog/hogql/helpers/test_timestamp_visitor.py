from datetime import UTC, datetime, timedelta, timezone

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
    parse_zoned_datetime_string,
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


class TestTimestampVisitorTypeCast(unittest.TestCase):
    """Regression tests for visit_type_cast / visit_try_cast methods.

    Postgres-style `::` casts (and CAST(...)) produce ast.TypeCast nodes that can reach these
    visitors via the sessions where-clause extractor. Before these methods existed the visitors
    raised NotImplementedError, crashing query execution.
    """

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
    def test_type_cast_does_not_raise_not_implemented(self, _name: str, make_visitor) -> None:
        type_cast = ast.TypeCast(expr=ast.Constant(value="2024-01-01"), type_name="DateTime")
        try_cast = ast.TryCast(expr=ast.Constant(value="2024-01-01"), type_name="DateTime")
        # Should not raise NotImplementedError
        make_visitor().visit(type_cast)
        make_visitor().visit(try_cast)

    @parameterized.expand(
        [
            (
                "type_cast_of_timestamp_field",
                ast.TypeCast(expr=ast.Field(chain=["timestamp"]), type_name="DateTime"),
                True,
            ),
            (
                "try_cast_of_timestamp_field",
                ast.TryCast(expr=ast.Field(chain=["timestamp"]), type_name="DateTime"),
                True,
            ),
            ("type_cast_of_constant", ast.TypeCast(expr=ast.Constant(value="2024-01-01"), type_name="DateTime"), False),
            ("try_cast_of_constant", ast.TryCast(expr=ast.Constant(value="2024-01-01"), type_name="DateTime"), False),
        ]
    )
    def test_cast_preserves_simple_timestamp_field_recognition(
        self, _name: str, node: ast.Expr, expected: bool
    ) -> None:
        # A cast around a timestamp field is still a timestamp field expression; a cast of a constant is not.
        self.assertEqual(is_simple_timestamp_field_expression(node, _make_hogql_context()), expected)


class TestIsTimeOrIntervalConstant(unittest.TestCase):
    @parameterized.expand(
        [
            ("type_cast_of_constant", ast.TypeCast(expr=ast.Constant(value="2024-01-01"), type_name="DateTime"), True),
            ("type_cast_of_field", ast.TypeCast(expr=ast.Field(chain=["timestamp"]), type_name="DateTime"), False),
            ("try_cast_of_constant", ast.TryCast(expr=ast.Constant(value="2024-01-01"), type_name="DateTime"), True),
            ("try_cast_of_field", ast.TryCast(expr=ast.Field(chain=["timestamp"]), type_name="DateTime"), False),
        ]
    )
    def test_cast_nodes(self, _name: str, node: ast.Expr, expected: bool) -> None:
        self.assertEqual(is_time_or_interval_constant(node), expected)

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


class TestParseZonedDatetimeString(unittest.TestCase):
    @parameterized.expand(
        [
            # Zone designator present and valid -> parsed to the exact aware instant.
            (
                "iso_utc_micros",
                "2026-06-30T09:59:12.988000Z",
                datetime(2026, 6, 30, 9, 59, 12, 988000, tzinfo=UTC),
            ),
            ("iso_utc_no_micros", "2026-06-30T09:59:12Z", datetime(2026, 6, 30, 9, 59, 12, tzinfo=UTC)),
            ("space_sep_utc", "2026-06-30 09:59:12Z", datetime(2026, 6, 30, 9, 59, 12, tzinfo=UTC)),
            (
                "offset_with_colon",
                "2026-06-30T09:59:12+02:00",
                datetime(2026, 6, 30, 9, 59, 12, tzinfo=timezone(timedelta(hours=2))),
            ),
            (
                "offset_no_colon",
                "2026-06-30T09:59:12-0800",
                datetime(2026, 6, 30, 9, 59, 12, tzinfo=timezone(timedelta(hours=-8))),
            ),
            (
                "offset_with_micros",
                "2026-06-30T09:59:12.5+02:00",
                datetime(2026, 6, 30, 9, 59, 12, 500000, tzinfo=timezone(timedelta(hours=2))),
            ),
            (
                "sub_microsecond_precision_truncated",
                "2026-06-30T09:59:12.988000123Z",
                datetime(2026, 6, 30, 9, 59, 12, 988000, tzinfo=UTC),
            ),
            # No zone designator -> ClickHouse parses these in the field timezone, must stay untouched.
            ("mysql_style", "2026-06-30 09:59:12", None),
            ("iso_no_zone", "2026-06-30T09:59:12", None),
            ("date_only", "2026-06-30", None),
            ("with_micros_no_zone", "2026-06-30 09:59:12.988000", None),
            # Shaped like a zoned datetime but not a real instant -> None keeps the strict path's clear error
            # instead of a silently-empty or silently-shifted result.
            ("month_out_of_range", "2026-13-45T99:99:99Z", None),
            ("day_month_swapped", "2026-30-06T00:00:00Z", None),
            ("impossible_offset", "2026-06-30T09:59:12+99:00", None),
            ("overflows_timezone_conversion", "0001-01-01T00:00:00+14:00", None),
            # Not a datetime at all.
            ("arbitrary_string_ending_z", "some_value_Z", None),
            ("empty", "", None),
            ("non_string", 12345, None),
            ("none", None, None),
        ]
    )
    def test_parse_zoned_datetime_string(self, _name: str, value: object, expected: datetime | None) -> None:
        self.assertEqual(parse_zoned_datetime_string(value), expected)
