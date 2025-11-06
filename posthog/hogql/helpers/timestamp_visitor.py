from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from posthog.hogql import ast
from posthog.hogql.ast import ArithmeticOperationOp
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField
from posthog.hogql.errors import NotImplementedError
from posthog.hogql.visitor import Visitor


def is_simple_timestamp_field_expression(
    expr: ast.Expr, context: HogQLContext, tombstone_string: Optional[str] = None
) -> bool:
    result = IsSimpleTimestampFieldExpressionVisitor(context, tombstone_string).visit(expr)
    return result


class IsSimpleTimestampFieldExpressionVisitor(Visitor[bool]):
    context: HogQLContext

    def __init__(self, context: HogQLContext, tombstone_string: Optional[str] = None):
        self.context = context
        self.tombstone_string = tombstone_string

    def visit_constant(self, node: ast.Constant) -> bool:
        return False

    def visit_select_query(self, node: ast.SelectQuery) -> bool:
        return False

    def visit_field(self, node: ast.Field) -> bool:
        if node.type and isinstance(node.type, ast.FieldType):
            resolved_field = node.type.resolve_database_field(self.context)
            if resolved_field and isinstance(resolved_field, DatabaseField) and resolved_field:
                return resolved_field.name in [
                    "$start_timestamp",
                    "$end_timestamp",
                    "min_timestamp",
                    "timestamp",
                    "min_first_timestamp",
                ]
        # no type information, so just use the name of the field
        return node.chain[-1] in [
            "$start_timestamp",
            "$end_timestamp",
            "min_timestamp",
            "timestamp",
            "min_first_timestamp",
        ]

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> bool:
        # only allow the min_timestamp field to be used on one side of the arithmetic operation
        return (
            self.visit(node.left)
            and is_time_or_interval_constant(node.right, self.tombstone_string)
            or (self.visit(node.right) and is_time_or_interval_constant(node.left, self.tombstone_string))
        )

    def visit_call(self, node: ast.Call) -> bool:
        # some functions count as a timestamp field expression if their first argument is
        if node.name in [
            "parseDateTime64BestEffortOrNull",
            "toDateTime",
            "toTimeZone",
            "assumeNotNull",
            "toStartOfDay",
            "toStartOfWeek",
            "toStartOfMonth",
            "toStartOfQuarter",
            "toStartOfYear",
        ]:
            return self.visit(node.args[0])

        if node.name in ["minus", "add"]:
            return self.visit_arithmetic_operation(
                ast.ArithmeticOperation(
                    op=ArithmeticOperationOp.Sub if node.name == "minus" else ArithmeticOperationOp.Add,
                    left=node.args[0],
                    right=node.args[1],
                )
            )

        # otherwise we don't know, so return False
        return False

    def visit_compare_operation(self, node: ast.CompareOperation) -> bool:
        return False

    def visit_between_expr(self, node: ast.BetweenExpr) -> bool:
        return False

    def visit_and(self, node: ast.And) -> bool:
        return False

    def visit_or(self, node: ast.Or) -> bool:
        return False

    def visit_not(self, node: ast.Not) -> bool:
        return False

    def visit_placeholder(self, node: ast.Placeholder) -> bool:
        raise Exception()

    def visit_alias(self, node: ast.Alias) -> bool:
        from posthog.hogql.database.schema.events import EventsTable
        from posthog.hogql.database.schema.session_replay_events import RawSessionReplayEventsTable
        from posthog.hogql.database.schema.sessions_v1 import SessionsTableV1
        from posthog.hogql.database.schema.sessions_v2 import SessionsTableV2
        from posthog.hogql.database.schema.sessions_v3 import SessionsTableV3

        if node.type and isinstance(node.type, ast.FieldAliasType):
            try:
                resolved_field = node.type.resolve_database_field(self.context)
            except NotImplementedError:
                return False

            table_type = node.type.resolve_table_type(self.context)
            if not table_type:
                return False
            if isinstance(table_type, ast.TableAliasType):
                table_type = table_type.table_type
            return (
                (
                    isinstance(table_type, ast.TableType)
                    and isinstance(table_type.table, EventsTable)
                    and resolved_field.name == "timestamp"
                )
                or (
                    isinstance(table_type, ast.LazyTableType)
                    and isinstance(table_type.table, SessionsTableV1)
                    and resolved_field.name in ("$start_timestamp", "$end_timestamp")
                )
                or (
                    isinstance(table_type, ast.LazyTableType)
                    and isinstance(table_type.table, SessionsTableV2)
                    # we guarantee that a session is < 24 hours, so with bufferDays being 3 above, we can use $end_timestamp too
                    and resolved_field.name in ("$start_timestamp", "$end_timestamp")
                )
                or (
                    isinstance(table_type, ast.LazyTableType)
                    and isinstance(table_type.table, SessionsTableV3)
                    # we guarantee that a session is < 24 hours, so with bufferDays being 3 above, we can use $end_timestamp too
                    and resolved_field.name in ("$start_timestamp", "$end_timestamp")
                )
                or (
                    isinstance(table_type, ast.TableType)
                    and isinstance(table_type.table, RawSessionReplayEventsTable)
                    and resolved_field.name == "min_first_timestamp"
                )
            )

        return self.visit(node.expr)

    def visit_tuple(self, node: ast.Tuple) -> bool:
        return all(self.visit(arg) for arg in node.exprs)

    def visit_array(self, node: ast.Array) -> bool:
        return all(self.visit(arg) for arg in node.exprs)


def is_time_or_interval_constant(expr: ast.Expr, tombstone_string: Optional[str] = None) -> bool:
    return IsTimeOrIntervalConstantVisitor(tombstone_string).visit(expr)


class IsTimeOrIntervalConstantVisitor(Visitor[bool]):
    def __init__(self, tombstone_string: Optional[str]):
        self.tombstone_string = tombstone_string

    def visit_constant(self, node: ast.Constant) -> bool:
        if self.tombstone_string is not None and node.value == self.tombstone_string:
            return False
        return True

    def visit_select_query(self, node: ast.SelectQuery) -> bool:
        return False

    def visit_compare_operation(self, node: ast.CompareOperation) -> bool:
        return self.visit(node.left) and self.visit(node.right)

    def visit_between_expr(self, node: ast.BetweenExpr) -> bool:
        return False

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> bool:
        return self.visit(node.left) and self.visit(node.right)

    def visit_call(self, node: ast.Call) -> bool:
        # some functions just return a constant
        if node.name in ["today", "now", "now64", "yesterday"]:
            return True
        # some functions return a constant if the first argument is a constant
        if node.name in [
            "parseDateTime64BestEffortOrNull",
            "toDateTime",
            "toDateTime64",
            "toTimeZone",
            "assumeNotNull",
        ] or any(node.name.startswith(prefix) for prefix in ["toInterval", "toStartOf"]):
            return self.visit(node.args[0])

        if node.name in ["minus", "add"]:
            return all(self.visit(arg) for arg in node.args)

        # otherwise we don't know, so return False
        return False

    def visit_field(self, node: ast.Field) -> bool:
        return False

    def visit_and(self, node: ast.And) -> bool:
        return False

    def visit_or(self, node: ast.Or) -> bool:
        return False

    def visit_not(self, node: ast.Not) -> bool:
        return False

    def visit_placeholder(self, node: ast.Placeholder) -> bool:
        raise Exception()

    def visit_alias(self, node: ast.Alias) -> bool:
        return self.visit(node.expr)

    def visit_tuple(self, node: ast.Tuple) -> bool:
        return all(self.visit(arg) for arg in node.exprs)

    def visit_array(self, node: ast.Array) -> bool:
        return all(self.visit(arg) for arg in node.exprs)


class IsStartOfPeriodConstantVisitor(Visitor[bool], ABC):
    constant_fns: list[str]
    constant_if_first_arg_constant_fns: list[str]
    interval_fns: list[str]

    def __init__(self, tombstone_string: Optional[str]):
        self.tombstone_string = tombstone_string

    @abstractmethod
    def check_parsed(self, parsed: datetime) -> bool:
        raise NotImplementedError("check_parsed must be implemented in subclasses")

    def visit_constant(self, node: ast.Constant) -> bool:
        if self.tombstone_string is not None and node.value == self.tombstone_string:
            return False
        if not isinstance(node.value, str):
            return False
        try:
            parsed = datetime.fromisoformat(node.value)
        except ValueError:
            return False
        return self.check_parsed(parsed)

    def visit_select_query(self, node: ast.SelectQuery) -> bool:
        return False

    def visit_compare_operation(self, node: ast.CompareOperation) -> bool:
        return False

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> bool:
        return False

    def visit_between_expr(self, node: ast.BetweenExpr) -> bool:
        return False

    def visit_call(self, node: ast.Call) -> bool:
        # some functions just return a constant
        if node.name in self.constant_fns:
            return True
        elif node.name in self.constant_if_first_arg_constant_fns:
            # these functions return the start of the day/week/month/quarter/year
            # note that we no longer care that it's a constant representing the start of the period, just that it's a constant now
            return is_time_or_interval_constant(node.args[0])
        # also handle toStartOfInterval functions, if the interval is valid
        elif node.name.startswith("toStartOfInterval") and len(node.args) == 2:
            if is_time_or_interval_constant(node.args[0]):
                interval = node.args[1]
                if isinstance(interval, ast.Call) and interval.name in self.interval_fns:
                    # these intervals are valid for start of day/week/month/quarter/year
                    num_intervals = interval.args[0]
                    if (
                        isinstance(num_intervals, ast.Constant)
                        and isinstance(num_intervals.value, int)
                        and num_intervals.value > 0
                    ):
                        return True
        # some functions return a constant if the first argument is a constant
        elif node.name in [
            "parseDateTime64BestEffortOrNull",
            "toDateTime",
            "toDateTime64",
            "assumeNotNull",
        ]:
            return self.visit(node.args[0])
        elif node.name == "toTimestamp" and len(node.args) == 2:
            # only allow UTC
            timezone = node.args[1]
            if isinstance(timezone, ast.Constant) and timezone.value == "UTC":
                return self.visit(node.args[0])

        return False

    def visit_field(self, node: ast.Field) -> bool:
        return False

    def visit_and(self, node: ast.And) -> bool:
        return False

    def visit_or(self, node: ast.Or) -> bool:
        return False

    def visit_not(self, node: ast.Not) -> bool:
        return False

    def visit_placeholder(self, node: ast.Placeholder) -> bool:
        raise Exception()

    def visit_alias(self, node: ast.Alias) -> bool:
        return self.visit(node.expr)

    def visit_tuple(self, node: ast.Tuple) -> bool:
        return False

    def visit_array(self, node: ast.Array) -> bool:
        return False


class IsStartOfDayConstantVisitor(IsStartOfPeriodConstantVisitor):
    constant_fns = ["today", "yesterday"]
    constant_if_first_arg_constant_fns = [
        "toStartOfDay",
        "toStartOfWeek",
        "toStartOfMonth",
        "toStartOfQuarter",
        "toStartOfYear",
    ]
    interval_fns = ["toIntervalDay", "toIntervalWeek", "toIntervalMonth", "toIntervalQuarter", "toIntervalYear"]

    def check_parsed(self, parsed: datetime) -> bool:
        return parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0 and parsed.microsecond == 0


def is_start_of_day_constant(expr: ast.Expr, tombstone_string: Optional[str] = None) -> bool:
    return IsStartOfDayConstantVisitor(tombstone_string).visit(expr)


class IsStartOfHourConstantVisitor(IsStartOfPeriodConstantVisitor):
    constant_fns = ["today", "yesterday"]
    constant_if_first_arg_constant_fns = [
        "toStartOfHour",
        "toStartOfDay",
        "toStartOfWeek",
        "toStartOfMonth",
        "toStartOfQuarter",
        "toStartOfYear",
    ]
    interval_fns = [
        "toIntervalHour",
        "toIntervalDay",
        "toIntervalWeek",
        "toIntervalMonth",
        "toIntervalQuarter",
        "toIntervalYear",
    ]

    def check_parsed(self, parsed: datetime) -> bool:
        return parsed.minute == 0 and parsed.second == 0 and parsed.microsecond == 0


def is_start_of_hour_constant(expr: ast.Expr, tombstone_string: Optional[str] = None) -> bool:
    return IsStartOfHourConstantVisitor(tombstone_string).visit(expr)


class IsEndOfPeriodConstantVisitor(Visitor[bool], ABC):
    @abstractmethod
    def check_parsed(self, parsed: datetime) -> bool:
        raise NotImplementedError("check_parsed must be implemented in subclasses")

    def __init__(self, tombstone_string: Optional[str]):
        self.tombstone_string = tombstone_string

    def visit_constant(self, node: ast.Constant) -> bool:
        if self.tombstone_string is not None and node.value == self.tombstone_string:
            return False
        if not isinstance(node.value, str):
            return False
        try:
            parsed = datetime.fromisoformat(node.value)
        except ValueError:
            return False
        # Check if the constant is 23:59:59 of any day. This is not exact, but this is how
        # our QueryDateRange class works, and we need to be compatible with that.
        return self.check_parsed(parsed)

    def visit_select_query(self, node: ast.SelectQuery) -> bool:
        return False

    def visit_compare_operation(self, node: ast.CompareOperation) -> bool:
        return False

    def visit_between_expr(self, node: ast.BetweenExpr) -> bool:
        return False

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> bool:
        return False

    def visit_call(self, node: ast.Call) -> bool:
        # there's no toEndOfDay function, so we're just checking the constant itself
        if node.name in [
            "parseDateTime64BestEffortOrNull",
            "toDateTime",
            "toDateTime64",
            "assumeNotNull",
        ]:
            return self.visit(node.args[0])
        elif node.name == "toTimestamp" and len(node.args) == 2:
            # only allow UTC
            timezone = node.args[1]
            if isinstance(timezone, ast.Constant) and timezone.value == "UTC":
                return self.visit(node.args[0])

        return False

    def visit_field(self, node: ast.Field) -> bool:
        return False

    def visit_and(self, node: ast.And) -> bool:
        return False

    def visit_or(self, node: ast.Or) -> bool:
        return False

    def visit_not(self, node: ast.Not) -> bool:
        return False

    def visit_placeholder(self, node: ast.Placeholder) -> bool:
        raise Exception()

    def visit_alias(self, node: ast.Alias) -> bool:
        return self.visit(node.expr)

    def visit_tuple(self, node: ast.Tuple) -> bool:
        return False

    def visit_array(self, node: ast.Array) -> bool:
        return False


class IsEndOfDayConstantVisitor(IsEndOfPeriodConstantVisitor):
    def check_parsed(self, parsed: datetime) -> bool:
        return parsed.hour == 23 and parsed.minute == 59 and parsed.second == 59


def is_end_of_day_constant(expr: ast.Expr, tombstone_string: Optional[str] = None) -> bool:
    return IsEndOfDayConstantVisitor(tombstone_string).visit(expr)


class IsEndOfHourConstantVisitor(IsEndOfPeriodConstantVisitor):
    def check_parsed(self, parsed: datetime) -> bool:
        return parsed.minute == 59 and parsed.second == 59


def is_end_of_hour_constant(expr: ast.Expr, tombstone_string: Optional[str] = None) -> bool:
    return IsEndOfHourConstantVisitor(tombstone_string).visit(expr)
