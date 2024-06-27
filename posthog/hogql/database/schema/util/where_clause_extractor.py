import random
import string
from typing import Optional, cast

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperationOp, ArithmeticOperationOp
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField, LazyJoinToAdd, LazyTableToAdd

from posthog.hogql.visitor import clone_expr, CloningVisitor, Visitor, TraversingVisitor

SESSION_BUFFER_DAYS = 3


class WhereClauseExtractor(CloningVisitor):
    """This class extracts reductive filters from the Where clause into a lazily joined table.

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
    capture_timestamp_comparisons: bool = False  # implement handle_timestamp_comparison if setting this to True
    tracked_tables: list[ast.LazyTable | ast.LazyJoin]
    tombstone_string: str

    def __init__(self, context: HogQLContext):
        super().__init__()
        self.context = context
        self.tracked_tables = []
        # A constant with this string will be used to escape early if we can't handle the query
        self.tombstone_string = (
            "__TOMBSTONE__" + ("".join(random.choices(string.ascii_uppercase + string.digits, k=10))) + "__"
        )

    def handle_timestamp_comparison(
        self, node: ast.CompareOperation, is_left_constant: bool, is_right_constant: bool
    ) -> Optional[ast.Expr]:
        raise NotImplementedError()  # handle this in a subclass if setting capture_timestamp_comparisons to True

    def add_local_tables(self, join_or_table: LazyJoinToAdd | LazyTableToAdd):
        """Add the tables whose filters to extract into a new where clause."""
        if isinstance(join_or_table, LazyJoinToAdd):
            if join_or_table.lazy_join not in self.tracked_tables:
                self.tracked_tables.append(join_or_table.lazy_join)
        elif isinstance(join_or_table, LazyTableToAdd):
            if join_or_table.lazy_table not in self.tracked_tables:
                self.tracked_tables.append(join_or_table.lazy_table)

    def get_inner_where(self, select_query: ast.SelectQuery) -> Optional[ast.Expr]:
        """Return the where clause that should be applied to the inner table. If None is returned, no pre-filtering is possible."""
        if not select_query.where and not select_query.prewhere:
            return None

        # visit the where clause
        wheres = []
        if select_query.where:
            wheres.append(select_query.where)
        if select_query.prewhere:
            wheres.append(select_query.prewhere)

        if len(wheres) == 1:
            where = self.visit(wheres[0])
        else:
            where = self.visit(ast.And(exprs=wheres))

        if isinstance(where, ast.Constant):
            return None

        return clone_expr(where, clear_types=True, clear_locations=True)

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.Expr:
        if has_tombstone(node, self.tombstone_string):
            return ast.Constant(value=self.tombstone_string)

        is_left_constant = is_time_or_interval_constant(node.left, self.tombstone_string)
        is_right_constant = is_time_or_interval_constant(node.right, self.tombstone_string)

        # just ignore constant comparison
        if is_left_constant and is_right_constant:
            return ast.Constant(value=True)

        # extract timestamps from the main query into e.g. the sessions subquery
        if self.capture_timestamp_comparisons:
            result = self.handle_timestamp_comparison(node, is_left_constant, is_right_constant)
            if result:
                return result

        # Check if any of the fields are a field on our requested table
        if len(self.tracked_tables) > 0:
            left = self.visit(node.left)
            right = self.visit(node.right)
            if has_tombstone(left, self.tombstone_string) or has_tombstone(right, self.tombstone_string):
                return ast.Constant(value=self.tombstone_string)
            return ast.CompareOperation(op=node.op, left=left, right=right)

        return ast.Constant(value=True)

    def visit_select_query(self, node: ast.SelectQuery) -> ast.Expr:
        # going too deep, bail
        return ast.Constant(value=True)

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> ast.Expr:
        # don't even try to handle complex logic
        return ast.Constant(value=True)

    def visit_not(self, node: ast.Not) -> ast.Expr:
        response = self.visit(node.expr)
        if has_tombstone(response, self.tombstone_string):
            return ast.Constant(value=self.tombstone_string)
        return ast.Not(expr=response)

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
        elif node.name == "like":
            return self.visit_compare_operation(
                ast.CompareOperation(op=CompareOperationOp.Like, left=node.args[0], right=node.args[1])
            )
        elif node.name == "notLike":
            return self.visit_compare_operation(
                ast.CompareOperation(op=CompareOperationOp.NotLike, left=node.args[0], right=node.args[1])
            )
        elif node.name == "ilike":
            return self.visit_compare_operation(
                ast.CompareOperation(op=CompareOperationOp.ILike, left=node.args[0], right=node.args[1])
            )
        elif node.name == "notIlike":
            return self.visit_compare_operation(
                ast.CompareOperation(op=CompareOperationOp.NotILike, left=node.args[0], right=node.args[1])
            )
        args = [self.visit(arg) for arg in node.args]
        if any(has_tombstone(arg, self.tombstone_string) for arg in args):
            return ast.Constant(value=self.tombstone_string)
        return ast.Call(name=node.name, args=args)

    def visit_field(self, node: ast.Field) -> ast.Expr:
        # if field in requested list
        type = node.type
        if isinstance(type, ast.PropertyType):
            type = type.field_type
        if isinstance(type, ast.FieldAliasType):
            type = type.type
        if isinstance(type, ast.FieldType):
            table_type = type.table_type
            if (isinstance(table_type, ast.LazyTableType) and table_type.table in self.tracked_tables) or (
                isinstance(table_type, ast.LazyJoinType) and table_type.lazy_join in self.tracked_tables
            ):
                new_field = cast(ast.Field, clone_expr(node))
                if isinstance(node.type, ast.PropertyType):
                    chain_length = len(node.type.chain) + 1
                else:
                    chain_length = 1
                new_field.chain = new_field.chain[-chain_length:]
                return new_field
        return ast.Constant(value=self.tombstone_string)

    def visit_constant(self, node: ast.Constant) -> ast.Expr:
        return ast.Constant(value=node.value)

    def visit_placeholder(self, node: ast.Placeholder) -> ast.Expr:
        raise Exception()  # this should never happen, as placeholders should be resolved before this runs

    def visit_and(self, node: ast.And) -> ast.Expr:
        exprs = [self.visit(expr) for expr in node.exprs]
        flattened = flatten_ands(exprs)

        filtered = []
        for expr in flattened:
            if isinstance(expr, ast.Constant):
                if is_not_truthy(expr.value):
                    return ast.Constant(value=False)
                # skip all tombstones
            else:
                filtered.append(expr)

        if len(filtered) == 0:
            return ast.Constant(value=False)
        elif len(filtered) == 1:
            return filtered[0]
        else:
            return ast.And(exprs=filtered)

    def visit_or(self, node: ast.Or) -> ast.Expr:
        exprs = [self.visit(expr) for expr in node.exprs]
        flattened = flatten_ors(exprs)

        filtered = []
        for expr in flattened:
            if has_tombstone(expr, self.tombstone_string):
                return ast.Constant(value=self.tombstone_string)
            if isinstance(expr, ast.Constant):
                if is_truthy(expr.value):
                    return ast.Constant(value=True)
            else:
                filtered.append(expr)

        if len(filtered) == 0:
            return ast.Constant(value=False)
        elif len(filtered) == 1:
            return filtered[0]
        else:
            return ast.Or(exprs=filtered)

    def visit_alias(self, node: ast.Alias) -> ast.Expr:
        return self.visit(node.expr)


class SessionMinTimestampWhereClauseExtractor(WhereClauseExtractor):
    capture_timestamp_comparisons = True
    timestamp_field: ast.Expr
    time_buffer: ast.Expr

    def __init__(self, context: HogQLContext):
        super().__init__(context)

    def handle_timestamp_comparison(
        self, node: ast.CompareOperation, is_left_constant: bool, is_right_constant: bool
    ) -> Optional[ast.Expr]:
        is_left_timestamp_field = is_simple_timestamp_field_expression(node.left, self.context, self.tombstone_string)
        is_right_timestamp_field = is_simple_timestamp_field_expression(node.right, self.context, self.tombstone_string)

        # handle the left side being a min_timestamp expression and the right being constant
        if is_left_timestamp_field and is_right_constant:
            if node.op == CompareOperationOp.Eq:
                return ast.And(
                    exprs=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.LtEq,
                            left=ast.ArithmeticOperation(
                                op=ast.ArithmeticOperationOp.Sub,
                                left=rewrite_timestamp_field(node.left, self.timestamp_field, self.context),
                                right=self.time_buffer,
                            ),
                            right=node.right,
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.GtEq,
                            left=ast.ArithmeticOperation(
                                op=ast.ArithmeticOperationOp.Add,
                                left=rewrite_timestamp_field(node.left, self.timestamp_field, self.context),
                                right=self.time_buffer,
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
                        left=rewrite_timestamp_field(node.left, self.timestamp_field, self.context),
                        right=self.time_buffer,
                    ),
                    right=node.right,
                )
            elif node.op == CompareOperationOp.Lt or node.op == CompareOperationOp.LtEq:
                return ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Sub,
                        left=rewrite_timestamp_field(node.left, self.timestamp_field, self.context),
                        right=self.time_buffer,
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
        return None


class SessionMinTimestampWhereClauseExtractorV1(SessionMinTimestampWhereClauseExtractor):
    timestamp_field = ast.Field(chain=["raw_sessions", "min_timestamp"])
    time_buffer = ast.Call(name="toIntervalDay", args=[ast.Constant(value=SESSION_BUFFER_DAYS)])


class SessionMinTimestampWhereClauseExtractorV2(SessionMinTimestampWhereClauseExtractor):
    timestamp_field = ast.Call(
        name="fromUnixTimestamp",
        args=[
            ast.Call(
                name="intDiv",
                args=[
                    ast.Call(
                        name="_toUInt64",
                        args=[
                            ast.Call(
                                name="bitShiftRight",
                                args=[ast.Field(chain=["raw_sessions", "session_id_v7"]), ast.Constant(value=80)],
                            )
                        ],
                    ),
                    ast.Constant(value=1000),
                ],
            )
        ],
    )
    time_buffer = ast.Call(name="toIntervalDay", args=[ast.Constant(value=SESSION_BUFFER_DAYS)])


def has_tombstone(expr: ast.Expr, tombstone_string: str) -> bool:
    visitor = HasTombstoneVisitor(tombstone_string)
    visitor.visit(expr)
    return visitor.has_tombstone


class HasTombstoneVisitor(TraversingVisitor):
    has_tombstone = False
    tombstone_string: str

    def __init__(self, tombstone_string: str):
        self.tombstone_string = tombstone_string

    def visit_constant(self, node: ast.Constant):
        if node.value == self.tombstone_string:
            self.has_tombstone = True


def is_time_or_interval_constant(expr: ast.Expr, tombstone_string: str) -> bool:
    return IsTimeOrIntervalConstantVisitor(tombstone_string).visit(expr)


class IsTimeOrIntervalConstantVisitor(Visitor[bool]):
    def __init__(self, tombstone_string: str):
        self.tombstone_string = tombstone_string

    def visit_constant(self, node: ast.Constant) -> bool:
        if node.value == self.tombstone_string:
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

    def visit_tuple(self, node: ast.Tuple) -> bool:
        return all(self.visit(arg) for arg in node.exprs)


def is_simple_timestamp_field_expression(expr: ast.Expr, context: HogQLContext, tombstone_string: str) -> bool:
    return IsSimpleTimestampFieldExpressionVisitor(context, tombstone_string).visit(expr)


class IsSimpleTimestampFieldExpressionVisitor(Visitor[bool]):
    context: HogQLContext

    def __init__(self, context: HogQLContext, tombstone_string: str):
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
                return resolved_field.name in ["$start_timestamp", "min_timestamp", "timestamp", "min_first_timestamp"]
        # no type information, so just use the name of the field
        return node.chain[-1] in ["$start_timestamp", "min_timestamp", "timestamp", "min_first_timestamp"]

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
                    and resolved_field.name == "$start_timestamp"
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


def rewrite_timestamp_field(expr: ast.Expr, timestamp_field: ast.Expr, context: HogQLContext) -> ast.Expr:
    return RewriteTimestampFieldVisitor(context, timestamp_field).visit(expr)


class RewriteTimestampFieldVisitor(CloningVisitor):
    context: HogQLContext
    timestamp_field: ast.Expr

    def __init__(self, context: HogQLContext, timestamp_field: ast.Expr, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.context = context
        self.timestamp_field = timestamp_field

    def visit_field(self, node: ast.Field) -> ast.Expr:
        from posthog.hogql.database.schema.events import EventsTable
        from posthog.hogql.database.schema.sessions_v1 import SessionsTableV1
        from posthog.hogql.database.schema.session_replay_events import RawSessionReplayEventsTable

        if node.type and isinstance(node.type, ast.FieldType):
            resolved_field = node.type.resolve_database_field(self.context)
            table_type = node.type.resolve_table_type(self.context)
            if isinstance(table_type, ast.TableAliasType):
                table_type = table_type.table_type
            table = table_type.table
            if resolved_field and isinstance(resolved_field, DatabaseField):
                if (
                    (isinstance(table, EventsTable) and resolved_field.name == "timestamp")
                    or (isinstance(table, SessionsTableV1) and resolved_field.name == "$start_timestamp")
                    or (isinstance(table, RawSessionReplayEventsTable) and resolved_field.name == "min_first_timestamp")
                ):
                    return self.timestamp_field
        # no type information, so just use the name of the field
        if node.chain[-1] in ["$start_timestamp", "min_timestamp", "timestamp", "min_first_timestamp"]:
            return self.timestamp_field
        return node

    def visit_alias(self, node: ast.Alias) -> ast.Expr:
        return self.visit(node.expr)


def flatten_ands(exprs):
    flattened = []
    for expr in exprs:
        if isinstance(expr, ast.And):
            flattened.extend(flatten_ands(expr.exprs))
        else:
            flattened.append(expr)
    return flattened


def flatten_ors(exprs):
    flattened = []
    for expr in exprs:
        if isinstance(expr, ast.Or):
            flattened.extend(flatten_ors(expr.exprs))
        else:
            flattened.append(expr)
    return flattened


def is_not_truthy(value):
    return value is False or value is None or value == 0


def is_truthy(value):
    return not is_not_truthy(value)
