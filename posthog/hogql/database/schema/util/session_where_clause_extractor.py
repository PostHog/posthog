from dataclasses import dataclass
from typing import Optional

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperationOp, ArithmeticOperationOp
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField

from posthog.hogql.visitor import clone_expr, CloningVisitor, Visitor

SESSION_BUFFER_DAYS = 3


@dataclass
class SessionMinTimestampWhereClauseExtractor(CloningVisitor):
    """This class extracts the Where clause from the lazy sessions table, to the clickhouse sessions table.

    The sessions table in Clickhouse is an AggregatingMergeTree, and will have one row per session per day. This means that
    when we want to query sessions, we need to pre-group these rows, so that we only have one row per session.

    We hide this detail using a lazy table, but to make querying the underlying Clickhouse table faster, we can inline the
    min_timestamp where conditions from the select on the outer lazy table to the select on the inner real table.

    This class is called on the select query of the lazy table, and will return the where clause that should be applied to
    the inner table.

    As a query can be unreasonably complex, we only handle simple cases, but this class is designed to fail-safe. If it
    can't reason about a particular expression, it will just return a constant True, i.e. fetch more rows than necessary.

    This means that we can incrementally add support for more complex queries, without breaking existing queries, by
    handling more cases.

    Some examples of failing-safe:

    `SELECT * FROM sessions where min_timestamp > '2022-01-01' AND f(session_id)`
    only the` min_timestamp > '2022-01-01'` part is relevant, so we can ignore the `f(session_id)` part, and it is safe
    to replace it with a constant True, which collapses the AND to just the `min_timestamp > '2022-01-01'` part.

    `SELECT * FROM sessions where min_timestamp > '2022-01-01' OR f(session_id)`
    only the` min_timestamp > '2022-01-01'` part is relevant, and turning the `f(session_id)` part into a constant True
    would collapse the OR to True. In this case we return None as no pre-filtering is possible.

    All min_timestamp comparisons are given a buffer of SESSION_BUFFER_DAYS each side, to ensure that we collect all the
    relevant rows for each session.
    """

    context: HogQLContext
    clear_types: bool = False
    clear_locations: bool = False

    def get_inner_where(self, parsed_query: ast.SelectQuery) -> Optional[ast.Expr]:
        if not parsed_query.where:
            return None

        # visit the where clause
        where = self.visit(parsed_query.where)

        if isinstance(where, ast.Constant):
            return None

        return clone_expr(where, clear_types=True, clear_locations=True)

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.Expr:
        is_left_constant = is_time_or_interval_constant(node.left)
        is_right_constant = is_time_or_interval_constant(node.right)
        is_left_timestamp_field = is_simple_timestamp_field_expression(node.left, self.context)
        is_right_timestamp_field = is_simple_timestamp_field_expression(node.right, self.context)

        if is_left_constant and is_right_constant:
            # just ignore this comparison
            return ast.Constant(value=True)

        # handle the left side being a min_timestamp expression and the right being constant
        if is_left_timestamp_field and is_right_constant:
            if node.op == CompareOperationOp.Eq:
                return ast.And(
                    exprs=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.LtEq,
                            left=ast.ArithmeticOperation(
                                op=ast.ArithmeticOperationOp.Sub,
                                left=rewrite_timestamp_field(node.left, self.context),
                                right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=SESSION_BUFFER_DAYS)]),
                            ),
                            right=node.right,
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.GtEq,
                            left=ast.ArithmeticOperation(
                                op=ast.ArithmeticOperationOp.Add,
                                left=rewrite_timestamp_field(node.left, self.context),
                                right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=SESSION_BUFFER_DAYS)]),
                            ),
                            right=node.right,
                        ),
                    ]
                )
            elif node.op == CompareOperationOp.Gt or node.op == CompareOperationOp.GtEq:
                return ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Add,
                        left=rewrite_timestamp_field(node.left, self.context),
                        right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=SESSION_BUFFER_DAYS)]),
                    ),
                    right=node.right,
                )
            elif node.op == CompareOperationOp.Lt or node.op == CompareOperationOp.LtEq:
                return ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Sub,
                        left=rewrite_timestamp_field(node.left, self.context),
                        right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=SESSION_BUFFER_DAYS)]),
                    ),
                    right=node.right,
                )
        elif is_right_timestamp_field and is_left_constant:
            # let's not duplicate the logic above, instead just flip and it and recurse
            if node.op in [
                CompareOperationOp.Eq,
                CompareOperationOp.Lt,
                CompareOperationOp.LtEq,
                CompareOperationOp.Gt,
                CompareOperationOp.GtEq,
            ]:
                return self.visit(
                    ast.CompareOperation(
                        op=CompareOperationOp.Eq
                        if node.op == CompareOperationOp.Eq
                        else CompareOperationOp.Lt
                        if node.op == CompareOperationOp.Gt
                        else CompareOperationOp.LtEq
                        if node.op == CompareOperationOp.GtEq
                        else CompareOperationOp.Gt
                        if node.op == CompareOperationOp.Lt
                        else CompareOperationOp.GtEq,
                        left=node.right,
                        right=node.left,
                    )
                )

        return ast.Constant(value=True)

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> ast.Expr:
        # don't even try to handle complex logic
        return ast.Constant(value=True)

    def visit_not(self, node: ast.Not) -> ast.Expr:
        return ast.Constant(value=True)

    def visit_call(self, node: ast.Call) -> ast.Expr:
        if node.name == "and":
            return self.visit_and(ast.And(exprs=node.args))
        elif node.name == "or":
            return self.visit_or(ast.Or(exprs=node.args))
        elif node.name == "greaterOrEquals":
            return self.visit_compare_operation(
                ast.CompareOperation(op=CompareOperationOp.GtEq, left=node.args[0], right=node.args[1])
            )
        elif node.name == "greater":
            return self.visit_compare_operation(
                ast.CompareOperation(op=CompareOperationOp.Gt, left=node.args[0], right=node.args[1])
            )
        elif node.name == "lessOrEquals":
            return self.visit_compare_operation(
                ast.CompareOperation(op=CompareOperationOp.LtEq, left=node.args[0], right=node.args[1])
            )
        elif node.name == "less":
            return self.visit_compare_operation(
                ast.CompareOperation(op=CompareOperationOp.Lt, left=node.args[0], right=node.args[1])
            )
        elif node.name == "equals":
            return self.visit_compare_operation(
                ast.CompareOperation(op=CompareOperationOp.Eq, left=node.args[0], right=node.args[1])
            )
        return ast.Constant(value=True)

    def visit_field(self, node: ast.Field) -> ast.Expr:
        return ast.Constant(value=True)

    def visit_constant(self, node: ast.Constant) -> ast.Expr:
        return ast.Constant(value=True)

    def visit_placeholder(self, node: ast.Placeholder) -> ast.Expr:
        raise Exception()  # this should never happen, as placeholders should be resolved before this runs

    def visit_and(self, node: ast.And) -> ast.Expr:
        exprs = [self.visit(expr) for expr in node.exprs]

        flattened = []
        for expr in exprs:
            if isinstance(expr, ast.And):
                flattened.extend(expr.exprs)
            else:
                flattened.append(expr)

        if any(isinstance(expr, ast.Constant) and expr.value is False for expr in flattened):
            return ast.Constant(value=False)

        filtered = [expr for expr in flattened if not isinstance(expr, ast.Constant) or expr.value is not True]
        if len(filtered) == 0:
            return ast.Constant(value=True)
        elif len(filtered) == 1:
            return filtered[0]
        else:
            return ast.And(exprs=filtered)

    def visit_or(self, node: ast.Or) -> ast.Expr:
        exprs = [self.visit(expr) for expr in node.exprs]

        flattened = []
        for expr in exprs:
            if isinstance(expr, ast.Or):
                flattened.extend(expr.exprs)
            else:
                flattened.append(expr)

        if any(isinstance(expr, ast.Constant) and expr.value is True for expr in flattened):
            return ast.Constant(value=True)

        filtered = [expr for expr in flattened if not isinstance(expr, ast.Constant) or expr.value is not False]
        if len(filtered) == 0:
            return ast.Constant(value=False)
        elif len(filtered) == 1:
            return filtered[0]
        else:
            return ast.Or(exprs=filtered)

    def visit_alias(self, node: ast.Alias) -> ast.Expr:
        return self.visit(node.expr)


def is_time_or_interval_constant(expr: ast.Expr) -> bool:
    return IsTimeOrIntervalConstantVisitor().visit(expr)


class IsTimeOrIntervalConstantVisitor(Visitor[bool]):
    def visit_constant(self, node: ast.Constant) -> bool:
        return True

    def visit_select_query(self, node: ast.SelectQuery) -> bool:
        return False

    def visit_compare_operation(self, node: ast.CompareOperation) -> bool:
        return self.visit(node.left) and self.visit(node.right)

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> bool:
        return self.visit(node.left) and self.visit(node.right)

    def visit_call(self, node: ast.Call) -> bool:
        # some functions just return a constant
        if node.name in ["today", "now"]:
            return True
        # some functions return a constant if the first argument is a constant
        if node.name in [
            "parseDateTime64BestEffortOrNull",
            "toDateTime",
            "toTimeZone",
            "assumeNotNull",
            "toIntervalYear",
            "toIntervalMonth",
            "toIntervalWeek",
            "toIntervalDay",
            "toIntervalHour",
            "toIntervalMinute",
            "toIntervalSecond",
            "toStartOfDay",
            "toStartOfWeek",
            "toStartOfMonth",
            "toStartOfQuarter",
            "toStartOfYear",
        ]:
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


def is_simple_timestamp_field_expression(expr: ast.Expr, context: HogQLContext) -> bool:
    return IsSimpleTimestampFieldExpressionVisitor(context).visit(expr)


@dataclass
class IsSimpleTimestampFieldExpressionVisitor(Visitor[bool]):
    context: HogQLContext

    def visit_constant(self, node: ast.Constant) -> bool:
        return False

    def visit_select_query(self, node: ast.SelectQuery) -> bool:
        return False

    def visit_field(self, node: ast.Field) -> bool:
        if node.type and isinstance(node.type, ast.FieldType):
            resolved_field = node.type.resolve_database_field(self.context)
            if resolved_field and isinstance(resolved_field, DatabaseField) and resolved_field:
                return resolved_field.name in ["$start_timestamp", "min_timestamp", "timestamp"]
        # no type information, so just use the name of the field
        return node.chain[-1] in ["$start_timestamp", "min_timestamp", "timestamp"]

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> bool:
        # only allow the min_timestamp field to be used on one side of the arithmetic operation
        return (
            self.visit(node.left)
            and is_time_or_interval_constant(node.right)
            or (self.visit(node.right) and is_time_or_interval_constant(node.left))
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
        from posthog.hogql.database.schema.sessions import SessionsTable

        if node.type and isinstance(node.type, ast.FieldAliasType):
            resolved_field = node.type.resolve_database_field(self.context)
            table_type = node.type.resolve_table_type(self.context)
            if not table_type:
                return False
            if isinstance(table_type, ast.TableAliasType):
                table_type = table_type.table_type
            return (
                isinstance(table_type, ast.TableType)
                and isinstance(table_type.table, EventsTable)
                and resolved_field.name == "timestamp"
            ) or (
                isinstance(table_type, ast.LazyTableType)
                and isinstance(table_type.table, SessionsTable)
                and resolved_field.name == "$start_timestamp"
            )

        return self.visit(node.expr)


def rewrite_timestamp_field(expr: ast.Expr, context: HogQLContext) -> ast.Expr:
    return RewriteTimestampFieldVisitor(context).visit(expr)


class RewriteTimestampFieldVisitor(CloningVisitor):
    context: HogQLContext

    def __init__(self, context: HogQLContext, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.context = context

    def visit_field(self, node: ast.Field) -> ast.Field:
        from posthog.hogql.database.schema.events import EventsTable
        from posthog.hogql.database.schema.sessions import SessionsTable

        if node.type and isinstance(node.type, ast.FieldType):
            resolved_field = node.type.resolve_database_field(self.context)
            table_type = node.type.resolve_table_type(self.context)
            if isinstance(table_type, ast.TableAliasType):
                table_type = table_type.table_type
            table = table_type.table
            if resolved_field and isinstance(resolved_field, DatabaseField):
                if (isinstance(table, EventsTable) and resolved_field.name == "timestamp") or (
                    isinstance(table, SessionsTable) and resolved_field.name == "$start_timestamp"
                ):
                    return ast.Field(chain=["raw_sessions", "min_timestamp"])
        # no type information, so just use the name of the field
        if node.chain[-1] in ["$start_timestamp", "min_timestamp", "timestamp"]:
            return ast.Field(chain=["raw_sessions", "min_timestamp"])
        return node

    def visit_alias(self, node: ast.Alias) -> ast.Expr:
        return self.visit(node.expr)
