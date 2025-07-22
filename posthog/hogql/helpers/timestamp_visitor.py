from typing import Optional

from posthog.hogql import ast
from posthog.hogql.ast import ArithmeticOperationOp
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField
from posthog.hogql.visitor import Visitor


def is_simple_timestamp_field_expression(expr: ast.Expr, context: HogQLContext, tombstone_string: Optional[str] = None) -> bool:
    result = IsSimpleTimestampFieldExpressionVisitor(context, tombstone_string).visit(expr)
    return result


class IsSimpleTimestampFieldExpressionVisitor(Visitor[bool]):
    context: HogQLContext

    def __init__(self, context: HogQLContext, tombstone_string: Optional[str]):
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
        from posthog.hogql.database.schema.sessions_v1 import SessionsTableV1
        from posthog.hogql.database.schema.sessions_v2 import SessionsTableV2

        from posthog.hogql.database.schema.session_replay_events import RawSessionReplayEventsTable

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

    def visit_array(self, node: ast.Tuple) -> bool:
        return all(self.visit(arg) for arg in node.exprs)

