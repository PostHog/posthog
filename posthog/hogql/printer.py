import re
from dataclasses import dataclass
from datetime import datetime, date
from difflib import get_close_matches
from typing import List, Literal, Optional, Union, cast
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.constants import (
    MAX_SELECT_RETURNED_ROWS,
    HogQLGlobalSettings,
)
from posthog.hogql.functions import (
    ADD_OR_NULL_DATETIME_FUNCTIONS,
    HOGQL_CLICKHOUSE_FUNCTIONS,
    FIRST_ARG_DATETIME_FUNCTIONS,
    HOGQL_AGGREGATIONS,
    HOGQL_POSTHOG_FUNCTIONS,
)
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import Table, FunctionCallTable, SavedQuery
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.errors import HogQLException
from posthog.hogql.escape_sql import (
    escape_clickhouse_identifier,
    escape_clickhouse_string,
    escape_hogql_identifier,
    escape_hogql_string,
)
from posthog.hogql.functions.mapping import ALL_EXPOSED_FUNCTION_NAMES, validate_function_args
from posthog.hogql.resolver import ResolverException, resolve_types
from posthog.hogql.resolver_utils import lookup_field_by_name
from posthog.hogql.transforms.in_cohort import resolve_in_cohorts
from posthog.hogql.transforms.lazy_tables import resolve_lazy_tables
from posthog.hogql.transforms.property_types import resolve_property_types
from posthog.hogql.visitor import Visitor, clone_expr
from posthog.models.property import PropertyName, TableColumn
from posthog.models.team.team import WeekStartDay
from posthog.models.utils import UUIDT
from posthog.utils import PersonOnEventsMode


def team_id_guard_for_table(table_type: Union[ast.TableType, ast.TableAliasType], context: HogQLContext) -> ast.Expr:
    """Add a mandatory "and(team_id, ...)" filter around the expression."""
    if not context.team_id:
        raise HogQLException("context.team_id not found")

    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Field(chain=["team_id"], type=ast.FieldType(name="team_id", table_type=table_type)),
        right=ast.Constant(value=context.team_id),
        type=ast.BooleanType(),
    )


def to_printed_hogql(query: ast.Expr, team_id: int) -> str:
    """Prints the HogQL query without mutating the node"""
    return print_ast(
        clone_expr(query),
        dialect="hogql",
        context=HogQLContext(team_id=team_id, enable_select_queries=True),
        pretty=True,
    )


def print_ast(
    node: ast.Expr,
    context: HogQLContext,
    dialect: Literal["hogql", "clickhouse"],
    stack: Optional[List[ast.SelectQuery]] = None,
    settings: Optional[HogQLGlobalSettings] = None,
    pretty: bool = False,
) -> str:
    prepared_ast = prepare_ast_for_printing(node=node, context=context, dialect=dialect, stack=stack, settings=settings)
    return print_prepared_ast(
        node=prepared_ast,
        context=context,
        dialect=dialect,
        stack=stack,
        settings=settings,
        pretty=pretty,
    )


def prepare_ast_for_printing(
    node: ast.Expr,
    context: HogQLContext,
    dialect: Literal["hogql", "clickhouse"],
    stack: Optional[List[ast.SelectQuery]] = None,
    settings: Optional[HogQLGlobalSettings] = None,
) -> ast.Expr:
    with context.timings.measure("create_hogql_database"):
        context.database = context.database or create_hogql_database(context.team_id, context.modifiers)

    with context.timings.measure("resolve_types"):
        node = resolve_types(node, context, scopes=[node.type for node in stack] if stack else None)
    if context.modifiers.inCohortVia == "leftjoin":
        with context.timings.measure("resolve_in_cohorts"):
            resolve_in_cohorts(node, stack, context)
    if dialect == "clickhouse":
        with context.timings.measure("resolve_property_types"):
            node = resolve_property_types(node, context)
        with context.timings.measure("resolve_lazy_tables"):
            resolve_lazy_tables(node, stack, context)

        # We support global query settings, and local subquery settings.
        # If the global query is a select query with settings, merge the two.
        if isinstance(node, ast.SelectQuery) and node.settings is not None and settings is not None:
            for key, value in node.settings.model_dump().items():
                if value is not None:
                    settings.__setattr__(key, value)
            node.settings = None

    # We add a team_id guard right before printing. It's not a separate step here.
    return node


def print_prepared_ast(
    node: ast.Expr,
    context: HogQLContext,
    dialect: Literal["hogql", "clickhouse"],
    stack: Optional[List[ast.SelectQuery]] = None,
    settings: Optional[HogQLGlobalSettings] = None,
    pretty: bool = False,
) -> str:
    with context.timings.measure("printer"):
        # _Printer also adds a team_id guard if printing clickhouse
        return _Printer(
            context=context,
            dialect=dialect,
            stack=stack or [],
            settings=settings,
            pretty=pretty,
        ).visit(node)


@dataclass
class JoinExprResponse:
    printed_sql: str
    where: Optional[ast.Expr] = None


class _Printer(Visitor):
    # NOTE: Call "print_ast()", not this class directly.

    def __init__(
        self,
        context: HogQLContext,
        dialect: Literal["hogql", "clickhouse"],
        stack: Optional[List[AST]] = None,
        settings: Optional[HogQLGlobalSettings] = None,
        pretty: bool = False,
    ):
        self.context = context
        self.dialect = dialect
        self.stack: List[AST] = stack or []  # Keep track of all traversed nodes.
        self.settings = settings
        self.pretty = pretty
        self._indent = -1
        self.tab_size = 4

    def indent(self, extra: int = 0):
        return " " * self.tab_size * (self._indent + extra)

    def visit(self, node: AST):
        self.stack.append(node)
        self._indent += 1
        response = super().visit(node)
        self._indent -= 1
        self.stack.pop()

        if len(self.stack) == 0 and self.dialect == "clickhouse" and self.settings:
            if not isinstance(node, ast.SelectQuery) and not isinstance(node, ast.SelectUnionQuery):
                raise HogQLException("Settings can only be applied to SELECT queries")
            settings = self._print_settings(self.settings)
            if settings is not None:
                response += " " + settings

        return response

    def visit_select_union_query(self, node: ast.SelectUnionQuery):
        self._indent -= 1
        queries = [self.visit(expr) for expr in node.select_queries]
        if self.pretty:
            query = f"\n{self.indent(1)}UNION ALL\n{self.indent(1)}".join([query.strip() for query in queries])
        else:
            query = " UNION ALL ".join(queries)
        self._indent += 1
        if len(self.stack) > 1:
            return f"({query.strip()})"
        return query

    def visit_select_query(self, node: ast.SelectQuery):
        if self.dialect == "clickhouse":
            if not self.context.enable_select_queries:
                raise HogQLException("Full SELECT queries are disabled if context.enable_select_queries is False")
            if not self.context.team_id:
                raise HogQLException("Full SELECT queries are disabled if context.team_id is not set")

        # if we are the first parsed node in the tree, or a child of a SelectUnionQuery, mark us as a top level query
        part_of_select_union = len(self.stack) >= 2 and isinstance(self.stack[-2], ast.SelectUnionQuery)
        is_top_level_query = len(self.stack) <= 1 or (len(self.stack) == 2 and part_of_select_union)

        # We will add extra clauses onto this from the joined tables
        where = node.where

        joined_tables = []
        next_join = node.select_from
        while isinstance(next_join, ast.JoinExpr):
            if next_join.type is None:
                if self.dialect == "clickhouse":
                    raise HogQLException("Printing queries with a FROM clause is not permitted before type resolution")

            visited_join = self.visit_join_expr(next_join)
            joined_tables.append(visited_join.printed_sql)

            # This is an expression we must add to the SELECT's WHERE clause to limit results, like the team ID guard.
            extra_where = visited_join.where
            if extra_where is None:
                pass
            elif isinstance(extra_where, ast.Expr):
                if where is None:
                    where = extra_where
                elif isinstance(where, ast.And):
                    where = ast.And(exprs=[extra_where] + where.exprs)
                else:
                    where = ast.And(exprs=[extra_where, where])
            else:
                raise HogQLException(f"Invalid where of type {type(extra_where).__name__} returned by join_expr")

            next_join = next_join.next_join

        columns = [self.visit(column) for column in node.select] if node.select else ["1"]
        window = (
            ", ".join(
                [f"{self._print_identifier(name)} AS ({self.visit(expr)})" for name, expr in node.window_exprs.items()]
            )
            if node.window_exprs
            else None
        )
        prewhere = self.visit(node.prewhere) if node.prewhere else None
        where = self.visit(where) if where else None
        group_by = [self.visit(column) for column in node.group_by] if node.group_by else None
        having = self.visit(node.having) if node.having else None
        order_by = [self.visit(column) for column in node.order_by] if node.order_by else None

        array_join = ""
        if node.array_join_op is not None:
            if node.array_join_op not in (
                "ARRAY JOIN",
                "LEFT ARRAY JOIN",
                "INNER ARRAY JOIN",
            ):
                raise HogQLException(f"Invalid ARRAY JOIN operation: {node.array_join_op}")
            array_join = node.array_join_op
            if len(node.array_join_list) == 0:
                raise HogQLException(f"Invalid ARRAY JOIN without an array")
            array_join += f" {', '.join(self.visit(expr) for expr in node.array_join_list)}"

        space = f"\n{self.indent(1)}" if self.pretty else " "
        comma = f",\n{self.indent(1)}" if self.pretty else ", "

        clauses = [
            f"SELECT{space}{'DISTINCT ' if node.distinct else ''}{comma.join(columns)}",
            f"FROM{space}{' '.join(joined_tables)}" if len(joined_tables) > 0 else None,
            array_join if array_join else None,
            f"PREWHERE{space}" + prewhere if prewhere else None,
            f"WHERE{space}" + where if where else None,
            f"GROUP BY{space}{comma.join(group_by)}" if group_by and len(group_by) > 0 else None,
            f"HAVING{space}" + having if having else None,
            f"WINDOW{space}" + window if window else None,
            f"ORDER BY{space}{comma.join(order_by)}" if order_by and len(order_by) > 0 else None,
        ]

        limit = node.limit
        if self.context.limit_top_select and is_top_level_query:
            if limit is not None:
                if isinstance(limit, ast.Constant) and isinstance(limit.value, int):
                    limit.value = min(limit.value, MAX_SELECT_RETURNED_ROWS)
                else:
                    limit = ast.Call(
                        name="min2",
                        args=[ast.Constant(value=MAX_SELECT_RETURNED_ROWS), limit],
                    )
            else:
                limit = ast.Constant(value=MAX_SELECT_RETURNED_ROWS)

        if limit is not None:
            clauses.append(f"LIMIT {self.visit(limit)}")
            if node.limit_with_ties:
                clauses.append("WITH TIES")
            if node.offset is not None:
                clauses.append(f"OFFSET {self.visit(node.offset)}")
            if node.limit_by is not None:
                clauses.append(f"BY {', '.join([self.visit(expr) for expr in node.limit_by])}")

        if node.settings is not None and self.dialect == "clickhouse":
            settings = self._print_settings(node.settings)
            if settings is not None:
                clauses.append(settings)

        if self.pretty:
            response = "\n".join([f"{self.indent()}{clause}" for clause in clauses if clause is not None])
        else:
            response = " ".join([clause for clause in clauses if clause is not None])

        # If we are printing a SELECT subquery (not the first AST node we are visiting), wrap it in parentheses.
        if not part_of_select_union and not is_top_level_query:
            if self.pretty:
                response = f"({response.strip()})"
            else:
                response = f"({response})"

        return response

    def visit_join_expr(self, node: ast.JoinExpr) -> JoinExprResponse:
        # return constraints we must place on the select query
        extra_where: Optional[ast.Expr] = None

        join_strings = []

        if node.join_type is not None:
            join_strings.append(node.join_type)

        if isinstance(node.type, ast.TableAliasType) or isinstance(node.type, ast.TableType):
            table_type = node.type
            while isinstance(table_type, ast.TableAliasType):
                table_type = table_type.table_type

            if not isinstance(table_type, ast.TableType) and not isinstance(table_type, ast.LazyTableType):
                raise HogQLException(f"Invalid table type {type(table_type).__name__} in join_expr")

            # :IMPORTANT: This assures a "team_id" where clause is present on every selected table.
            # Skip function call tables like numbers(), s3(), etc.
            if (
                self.dialect == "clickhouse"
                and not isinstance(table_type.table, FunctionCallTable)
                and not isinstance(table_type.table, SavedQuery)
            ):
                extra_where = team_id_guard_for_table(node.type, self.context)

            if self.dialect == "clickhouse":
                sql = table_type.table.to_printed_clickhouse(self.context)

                # Edge case. If we are joining an s3 table, we must wrap it in a subquery for the join to work
                if isinstance(table_type.table, S3Table) and (
                    node.next_join or node.join_type == "JOIN" or node.join_type == "GLOBAL JOIN"
                ):
                    sql = f"(SELECT * FROM {sql})"
            else:
                sql = table_type.table.to_printed_hogql()

            if isinstance(table_type.table, FunctionCallTable) and not isinstance(table_type.table, S3Table):
                if node.table_args is None:
                    raise HogQLException(f"Table function '{table_type.table.name}' requires arguments")

                if table_type.table.min_args is not None and (
                    node.table_args is None or len(node.table_args) < table_type.table.min_args
                ):
                    raise HogQLException(
                        f"Table function '{table_type.table.name}' requires at least {table_type.table.min_args} argument{'s' if table_type.table.min_args > 1 else ''}"
                    )
                if table_type.table.max_args is not None and (
                    node.table_args is None or len(node.table_args) > table_type.table.max_args
                ):
                    raise HogQLException(
                        f"Table function '{table_type.table.name}' requires at most {table_type.table.max_args} argument{'s' if table_type.table.max_args > 1 else ''}"
                    )
                if node.table_args is not None and len(node.table_args) > 0:
                    sql = f"{sql}({', '.join([self.visit(arg) for arg in node.table_args])})"
            elif node.table_args is not None:
                raise HogQLException(f"Table '{table_type.table.to_printed_hogql()}' does not accept arguments")

            join_strings.append(sql)

            if isinstance(node.type, ast.TableAliasType) and node.alias is not None and node.alias != sql:
                join_strings.append(f"AS {self._print_identifier(node.alias)}")

        elif isinstance(node.type, ast.SelectQueryType):
            join_strings.append(self.visit(node.table))

        elif isinstance(node.type, ast.SelectUnionQueryType):
            join_strings.append(self.visit(node.table))

        elif isinstance(node.type, ast.SelectQueryAliasType) and node.alias is not None:
            join_strings.append(self.visit(node.table))
            join_strings.append(f"AS {self._print_identifier(node.alias)}")

        elif isinstance(node.type, ast.LazyTableType):
            if self.dialect == "hogql":
                join_strings.append(self._print_identifier(node.type.table.to_printed_hogql()))
            else:
                raise HogQLException(f"Unexpected LazyTableType for: {node.type.table.to_printed_hogql()}")
        else:
            raise HogQLException(
                f"Only selecting from a table or a subquery is supported. Unexpected type: {node.type.__class__.__name__}"
            )

        if node.table_final:
            join_strings.append("FINAL")

        if node.sample is not None:
            sample_clause = self.visit_sample_expr(node.sample)
            if sample_clause is not None:
                join_strings.append(sample_clause)

        if node.constraint is not None:
            join_strings.append(f"ON {self.visit(node.constraint)}")

        return JoinExprResponse(printed_sql=" ".join(join_strings), where=extra_where)

    def visit_join_constraint(self, node: ast.JoinConstraint):
        return self.visit(node.expr)

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation):
        if node.op == ast.ArithmeticOperationOp.Add:
            return f"plus({self.visit(node.left)}, {self.visit(node.right)})"
        elif node.op == ast.ArithmeticOperationOp.Sub:
            return f"minus({self.visit(node.left)}, {self.visit(node.right)})"
        elif node.op == ast.ArithmeticOperationOp.Mult:
            return f"multiply({self.visit(node.left)}, {self.visit(node.right)})"
        elif node.op == ast.ArithmeticOperationOp.Div:
            return f"divide({self.visit(node.left)}, {self.visit(node.right)})"
        elif node.op == ast.ArithmeticOperationOp.Mod:
            return f"modulo({self.visit(node.left)}, {self.visit(node.right)})"
        else:
            raise HogQLException(f"Unknown ArithmeticOperationOp {node.op}")

    def visit_and(self, node: ast.And):
        return f"and({', '.join([self.visit(expr) for expr in node.exprs])})"

    def visit_or(self, node: ast.Or):
        return f"or({', '.join([self.visit(expr) for expr in node.exprs])})"

    def visit_not(self, node: ast.Not):
        return f"not({self.visit(node.expr)})"

    def visit_tuple_access(self, node: ast.TupleAccess):
        visited_tuple = self.visit(node.tuple)
        visited_index = int(str(node.index))
        if isinstance(node.tuple, ast.Field):
            return f"{visited_tuple}.{visited_index}"

        return f"({visited_tuple}).{visited_index}"

    def visit_tuple(self, node: ast.Tuple):
        return f"tuple({', '.join([self.visit(expr) for expr in node.exprs])})"

    def visit_array_access(self, node: ast.ArrayAccess):
        return f"{self.visit(node.array)}[{self.visit(node.property)}]"

    def visit_array(self, node: ast.Array):
        return f"[{', '.join([self.visit(expr) for expr in node.exprs])}]"

    def visit_lambda(self, node: ast.Lambda):
        identifiers = [self._print_identifier(arg) for arg in node.args]
        if len(identifiers) == 0:
            raise ValueError("Lambdas require at least one argument")
        elif len(identifiers) == 1:
            return f"{identifiers[0]} -> {self.visit(node.expr)}"
        return f"({', '.join(identifiers)}) -> {self.visit(node.expr)}"

    def visit_order_expr(self, node: ast.OrderExpr):
        return f"{self.visit(node.expr)} {node.order}"

    def visit_compare_operation(self, node: ast.CompareOperation):
        in_join_constraint = any(isinstance(item, ast.JoinConstraint) for item in self.stack)
        left = self.visit(node.left)
        right = self.visit(node.right)
        nullable_left = self._is_nullable(node.left)
        nullable_right = self._is_nullable(node.right)
        not_nullable = not nullable_left and not nullable_right

        # :HACK: until the new type system is out: https://github.com/PostHog/posthog/pull/17267
        # If we add a ifNull() around `events.timestamp`, we lose on the performance of the index.
        if ("toTimeZone(" in left and ".timestamp" in left) or ("toTimeZone(" in right and ".timestamp" in right):
            not_nullable = True

        constant_lambda = None
        value_if_one_side_is_null = False
        value_if_both_sides_are_null = False

        if node.op == ast.CompareOperationOp.Eq:
            op = f"equals({left}, {right})"
            constant_lambda = lambda left_op, right_op: left_op == right_op
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotEq:
            op = f"notEquals({left}, {right})"
            constant_lambda = lambda left_op, right_op: left_op != right_op
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.Like:
            op = f"like({left}, {right})"
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotLike:
            op = f"notLike({left}, {right})"
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.ILike:
            op = f"ilike({left}, {right})"
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotILike:
            op = f"notILike({left}, {right})"
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.In:
            op = f"in({left}, {right})"
        elif node.op == ast.CompareOperationOp.NotIn:
            op = f"notIn({left}, {right})"
        elif node.op == ast.CompareOperationOp.GlobalIn:
            op = f"globalIn({left}, {right})"
        elif node.op == ast.CompareOperationOp.GlobalNotIn:
            op = f"globalNotIn({left}, {right})"
        elif node.op == ast.CompareOperationOp.Regex:
            op = f"match({left}, {right})"
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotRegex:
            op = f"not(match({left}, {right}))"
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.IRegex:
            op = f"match({left}, concat('(?i)', {right}))"
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotIRegex:
            op = f"not(match({left}, concat('(?i)', {right})))"
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.Gt:
            op = f"greater({left}, {right})"
            constant_lambda = (
                lambda left_op, right_op: left_op > right_op if left_op is not None and right_op is not None else False
            )
        elif node.op == ast.CompareOperationOp.GtEq:
            op = f"greaterOrEquals({left}, {right})"
            constant_lambda = (
                lambda left_op, right_op: left_op >= right_op if left_op is not None and right_op is not None else False
            )
        elif node.op == ast.CompareOperationOp.Lt:
            op = f"less({left}, {right})"
            constant_lambda = (
                lambda left_op, right_op: left_op < right_op if left_op is not None and right_op is not None else False
            )
        elif node.op == ast.CompareOperationOp.LtEq:
            op = f"lessOrEquals({left}, {right})"
            constant_lambda = (
                lambda left_op, right_op: left_op <= right_op if left_op is not None and right_op is not None else False
            )
        else:
            raise HogQLException(f"Unknown CompareOperationOp: {node.op.name}")

        # Try to see if we can take shortcuts

        # Can we compare constants?
        if isinstance(node.left, ast.Constant) and isinstance(node.right, ast.Constant) and constant_lambda is not None:
            return "1" if constant_lambda(node.left.value, node.right.value) else "0"

        # Special cases when we should not add any null checks
        if in_join_constraint or self.dialect == "hogql" or not_nullable:
            return op

        # Special optimization for "Eq" operator
        if node.op == ast.CompareOperationOp.Eq:
            if isinstance(node.right, ast.Constant):
                if node.right.value is None:
                    return f"isNull({left})"
                return f"ifNull({op}, 0)"
            elif isinstance(node.left, ast.Constant):
                if node.left.value is None:
                    return f"isNull({right})"
                return f"ifNull({op}, 0)"
            return f"ifNull({op}, isNull({left}) and isNull({right}))"  # Worse case performance, but accurate

        # Special optimization for "NotEq" operator
        if node.op == ast.CompareOperationOp.NotEq:
            if isinstance(node.right, ast.Constant):
                if node.right.value is None:
                    return f"isNotNull({left})"
                return f"ifNull({op}, 1)"
            elif isinstance(node.left, ast.Constant):
                if node.left.value is None:
                    return f"isNotNull({right})"
                return f"ifNull({op}, 1)"
            return f"ifNull({op}, isNotNull({left}) or isNotNull({right}))"  # Worse case performance, but accurate

        # Return false if one, but only one of the two sides is a null constant
        if isinstance(node.right, ast.Constant) and node.right.value is None:
            # Both are a constant null
            if isinstance(node.left, ast.Constant) and node.left.value is None:
                return "1" if value_if_both_sides_are_null is True else "0"

            # Only the right side is null. Return a value only if the left side doesn't matter.
            if value_if_both_sides_are_null == value_if_one_side_is_null:
                return "1" if value_if_one_side_is_null is True else "0"
        elif isinstance(node.left, ast.Constant) and node.left.value is None:
            # Only the left side is null. Return a value only if the right side doesn't matter.
            if value_if_both_sides_are_null == value_if_one_side_is_null:
                return "1" if value_if_one_side_is_null is True else "0"

        # "in" and "not in" return 0/1 when the right operator is null, so optimize if the left operand is not nullable
        if node.op == ast.CompareOperationOp.In or node.op == ast.CompareOperationOp.NotIn:
            if not nullable_left or (isinstance(node.left, ast.Constant) and node.left.value is not None):
                return op

        # No constants, so check for nulls in SQL
        if value_if_one_side_is_null is True and value_if_both_sides_are_null is True:
            return f"ifNull({op}, 1)"
        elif value_if_one_side_is_null is True and value_if_both_sides_are_null is False:
            return f"ifNull({op}, isNotNull({left}) or isNotNull({right}))"
        elif value_if_one_side_is_null is False and value_if_both_sides_are_null is True:
            return f"ifNull({op}, isNull({left}) and isNull({right}))"  # Worse case performance, but accurate
        elif value_if_one_side_is_null is False and value_if_both_sides_are_null is False:
            return f"ifNull({op}, 0)"
        else:
            raise HogQLException("Impossible")

    def visit_constant(self, node: ast.Constant):
        if self.dialect == "hogql":
            # Inline everything in HogQL
            return self._print_escaped_string(node.value)
        elif (
            node.value is None
            or isinstance(node.value, bool)
            or isinstance(node.value, int)
            or isinstance(node.value, float)
            or isinstance(node.value, UUID)
            or isinstance(node.value, UUIDT)
            or isinstance(node.value, datetime)
            or isinstance(node.value, date)
        ):
            # Inline some permitted types in ClickHouse
            value = self._print_escaped_string(node.value)
            if "%" in value:
                # We don't know if this will be passed on as part of a legacy ClickHouse query or not.
                # Ban % to be on the safe side. Who knows how it can end up in a UUID or datetime for example.
                raise HogQLException(f"Invalid character '%' in constant: {value}")
            return value
        else:
            # Strings, lists, tuples, and any other random datatype printed in ClickHouse.
            return self.context.add_value(node.value)

    def visit_field(self, node: ast.Field):
        if node.type is None:
            field = ".".join([self._print_hogql_identifier_or_index(identifier) for identifier in node.chain])
            raise HogQLException(f"Field {field} has no type")

        if self.dialect == "hogql":
            if node.chain == ["*"]:
                return "*"
            # When printing HogQL, we print the properties out as a chain as they are.
            return ".".join([self._print_hogql_identifier_or_index(identifier) for identifier in node.chain])

        if node.type is not None:
            if isinstance(node.type, ast.LazyJoinType) or isinstance(node.type, ast.VirtualTableType):
                raise HogQLException(f"Can't select a table when a column is expected: {'.'.join(node.chain)}")

            return self.visit(node.type)
        else:
            raise HogQLException(f"Unknown Type, can not print {type(node.type).__name__}")

    def visit_call(self, node: ast.Call):
        if node.name in HOGQL_AGGREGATIONS:
            func_meta = HOGQL_AGGREGATIONS[node.name]

            validate_function_args(
                node.args,
                func_meta.min_args,
                func_meta.max_args,
                node.name,
                function_term="aggregation",
            )
            if func_meta.min_params:
                if node.params is None:
                    raise HogQLException(f"Aggregation '{node.name}' requires parameters in addition to arguments")
                validate_function_args(
                    node.params,
                    func_meta.min_params,
                    func_meta.max_params,
                    node.name,
                    function_term="aggregation",
                    argument_term="parameter",
                )

            # check that we're not running inside another aggregate
            for stack_node in self.stack:
                if stack_node != node and isinstance(stack_node, ast.Call) and stack_node.name in HOGQL_AGGREGATIONS:
                    raise HogQLException(
                        f"Aggregation '{node.name}' cannot be nested inside another aggregation '{stack_node.name}'."
                    )

            args = [self.visit(arg) for arg in node.args]
            params = [self.visit(param) for param in node.params] if node.params is not None else None

            params_part = f"({', '.join(params)})" if params is not None else ""
            args_part = f"({f'DISTINCT ' if node.distinct else ''}{', '.join(args)})"
            return f"{func_meta.clickhouse_name}{params_part}{args_part}"

        elif node.name in HOGQL_CLICKHOUSE_FUNCTIONS:
            func_meta = HOGQL_CLICKHOUSE_FUNCTIONS[node.name]

            validate_function_args(node.args, func_meta.min_args, func_meta.max_args, node.name)
            if func_meta.min_params:
                if node.params is None:
                    raise HogQLException(f"Function '{node.name}' requires parameters in addition to arguments")
                validate_function_args(
                    node.params,
                    func_meta.min_params,
                    func_meta.max_params,
                    node.name,
                    argument_term="parameter",
                )

            if self.dialect == "clickhouse":
                if node.name in FIRST_ARG_DATETIME_FUNCTIONS:
                    args: List[str] = []
                    for idx, arg in enumerate(node.args):
                        if idx == 0:
                            if isinstance(arg, ast.Call) and arg.name in ADD_OR_NULL_DATETIME_FUNCTIONS:
                                args.append(f"assumeNotNull(toDateTime({self.visit(arg)}))")
                            else:
                                args.append(f"toDateTime({self.visit(arg)}, 'UTC')")
                        else:
                            args.append(self.visit(arg))
                elif node.name == "concat":
                    args: List[str] = []
                    for arg in node.args:
                        if isinstance(arg, ast.Constant):
                            if arg.value is None:
                                args.append("''")
                            elif isinstance(arg.value, str):
                                args.append(self.visit(arg))
                            else:
                                args.append(f"toString({self.visit(arg)})")
                        elif isinstance(arg, ast.Call) and arg.name == "toString":
                            if len(arg.args) == 1 and isinstance(arg.args[0], ast.Constant):
                                if arg.args[0].value is None:
                                    args.append("''")
                                else:
                                    args.append(self.visit(arg))
                            else:
                                args.append(f"ifNull({self.visit(arg)}, '')")
                        else:
                            args.append(f"ifNull(toString({self.visit(arg)}), '')")
                else:
                    args = [self.visit(arg) for arg in node.args]

                relevant_clickhouse_name = func_meta.clickhouse_name
                if func_meta.overloads:
                    first_arg_constant_type = (
                        node.args[0].type.resolve_constant_type()
                        if len(node.args) > 0 and node.args[0].type is not None
                        else None
                    )

                    if first_arg_constant_type is not None:
                        for (
                            overload_types,
                            overload_clickhouse_name,
                        ) in func_meta.overloads:
                            if isinstance(first_arg_constant_type, overload_types):
                                relevant_clickhouse_name = overload_clickhouse_name
                                break  # Found an overload matching the first function org

                if func_meta.tz_aware:
                    if (relevant_clickhouse_name == "now64" and len(node.args) == 0) or (
                        relevant_clickhouse_name == "parseDateTime64BestEffortOrNull" and len(node.args) == 1
                    ):
                        args.append("6")  # These two CH functions require the precision argument before timezone
                    args.append(self.visit(ast.Constant(value=self._get_timezone())))
                if node.name == "toStartOfWeek" and len(node.args) == 1:
                    # If week mode hasn't been specified, use the project's default.
                    # For Monday-based weeks mode 3 is used (which is ISO 8601), for Sunday-based mode 0 (CH default)
                    args.insert(1, WeekStartDay(self._get_week_start_day()).clickhouse_mode)

                params = [self.visit(param) for param in node.params] if node.params is not None else None

                params_part = f"({', '.join(params)})" if params is not None else ""
                args_part = f"({', '.join(args)})"
                return f"{relevant_clickhouse_name}{params_part}{args_part}"
            else:
                return f"{node.name}({', '.join([self.visit(arg) for arg in node.args])})"
        elif node.name in HOGQL_POSTHOG_FUNCTIONS:
            raise HogQLException(f"Unexpected unresolved HogQL function '{node.name}(...)'")
        else:
            close_matches = get_close_matches(node.name, ALL_EXPOSED_FUNCTION_NAMES, 1)
            if len(close_matches) > 0:
                raise HogQLException(
                    f"Unsupported function call '{node.name}(...)'. Perhaps you meant '{close_matches[0]}(...)'?"
                )
            raise HogQLException(f"Unsupported function call '{node.name}(...)'")

    def visit_placeholder(self, node: ast.Placeholder):
        raise HogQLException(f"Placeholders, such as {{{node.field}}}, are not supported in this context")

    def visit_alias(self, node: ast.Alias):
        inside = self.visit(node.expr)
        if isinstance(node.expr, ast.Alias):
            inside = f"({inside})"
        alias = self._print_identifier(node.alias)
        return f"{inside} AS {alias}"

    def visit_table_type(self, type: ast.TableType):
        if self.dialect == "clickhouse":
            return type.table.to_printed_clickhouse(self.context)
        else:
            return type.table.to_printed_hogql()

    def visit_table_alias_type(self, type: ast.TableAliasType):
        return self._print_identifier(type.alias)

    def visit_lambda_argument_type(self, type: ast.LambdaArgumentType):
        return self._print_identifier(type.name)

    def visit_field_type(self, type: ast.FieldType):
        try:
            last_select = self._last_select()
            type_with_name_in_scope = lookup_field_by_name(last_select.type, type.name) if last_select else None
        except ResolverException:
            type_with_name_in_scope = None

        if (
            isinstance(type.table_type, ast.TableType)
            or isinstance(type.table_type, ast.TableAliasType)
            or isinstance(type.table_type, ast.VirtualTableType)
        ):
            resolved_field = type.resolve_database_field()
            if resolved_field is None:
                raise HogQLException(f'Can\'t resolve field "{type.name}" on table.')
            if isinstance(resolved_field, Table):
                if isinstance(type.table_type, ast.VirtualTableType):
                    return self.visit(ast.AsteriskType(table_type=ast.TableType(table=resolved_field)))
                else:
                    return self.visit(
                        ast.AsteriskType(
                            table_type=ast.TableAliasType(
                                table_type=ast.TableType(table=resolved_field),
                                alias=type.table_type.alias,
                            )
                        )
                    )

            # :KLUDGE: Legacy person properties handling. Only used within non-HogQL queries, such as insights.
            if (
                self.context.within_non_hogql_query
                and isinstance(type.table_type, ast.VirtualTableType)
                and type.name == "properties"
                and type.table_type.field == "poe"
            ):
                if self.context.modifiers.personsOnEventsMode != PersonOnEventsMode.DISABLED:
                    field_sql = "person_properties"
                else:
                    field_sql = "person_props"
            else:
                # this errors because resolved_field is of type ast.Alias and not a field - what's the best way to solve?
                field_sql = self._print_identifier(resolved_field.name)
                if self.context.within_non_hogql_query and type_with_name_in_scope == type:
                    # Do not prepend table name in non-hogql context. We don't know what it actually is.
                    return field_sql
                field_sql = f"{self.visit(type.table_type)}.{field_sql}"

        elif isinstance(type.table_type, ast.SelectQueryType) or isinstance(type.table_type, ast.SelectQueryAliasType):
            field_sql = self._print_identifier(type.name)
            if isinstance(type.table_type, ast.SelectQueryAliasType):
                field_sql = f"{self.visit(type.table_type)}.{field_sql}"

            # :KLUDGE: Legacy person properties handling. Only used within non-HogQL queries, such as insights.
            if self.context.within_non_hogql_query and field_sql == "events__pdi__person.properties":
                if self.context.modifiers.personsOnEventsMode != PersonOnEventsMode.DISABLED:
                    field_sql = "person_properties"
                else:
                    field_sql = "person_props"

        else:
            raise HogQLException(f"Unknown FieldType table type: {type.table_type.__class__.__name__}")

        return field_sql

    def visit_property_type(self, type: ast.PropertyType):
        if type.joined_subquery is not None and type.joined_subquery_field_name is not None:
            return f"{self._print_identifier(type.joined_subquery.alias)}.{self._print_identifier(type.joined_subquery_field_name)}"

        field_type = type.field_type
        field = field_type.resolve_database_field()

        # check for a materialised column
        table = field_type.table_type
        while isinstance(table, ast.TableAliasType):
            table = table.table_type

        # find a materialized property for the first part of the chain
        materialized_property_sql: Optional[str] = None
        if isinstance(table, ast.TableType):
            if self.dialect == "clickhouse":
                table_name = table.table.to_printed_clickhouse(self.context)
            else:
                table_name = table.table.to_printed_hogql()
            if field is None:
                raise HogQLException(f"Can't resolve field {field_type.name} on table {table_name}")
            field_name = cast(Union[Literal["properties"], Literal["person_properties"]], field.name)

            materialized_column = self._get_materialized_column(table_name, type.chain[0], field_name)
            if materialized_column:
                property_sql = self._print_identifier(materialized_column)
                property_sql = f"{self.visit(field_type.table_type)}.{property_sql}"
                materialized_property_sql = property_sql
        elif (
            self.context.within_non_hogql_query
            and (isinstance(table, ast.SelectQueryAliasType) and table.alias == "events__pdi__person")
            or (isinstance(table, ast.VirtualTableType) and table.field == "poe")
        ):
            # :KLUDGE: Legacy person properties handling. Only used within non-HogQL queries, such as insights.
            if self.context.modifiers.personsOnEventsMode != PersonOnEventsMode.DISABLED:
                materialized_column = self._get_materialized_column("events", type.chain[0], "person_properties")
            else:
                materialized_column = self._get_materialized_column("person", type.chain[0], "properties")
            if materialized_column:
                materialized_property_sql = self._print_identifier(materialized_column)

        args: List[str] = []
        if materialized_property_sql is not None:
            # When reading materialized columns, treat the values "" and "null" as NULL-s.
            # TODO: rematerialize all columns to support empty strings and "null" string values.
            materialized_property_sql = f"nullIf(nullIf({materialized_property_sql}, ''), 'null')"

            if len(type.chain) == 1:
                return materialized_property_sql
            else:
                for name in type.chain[1:]:
                    args.append(self.context.add_value(name))
                return self._unsafe_json_extract_trim_quotes(materialized_property_sql, args)

        for name in type.chain:
            args.append(self.context.add_value(name))
        return self._unsafe_json_extract_trim_quotes(self.visit(field_type), args)

    def visit_sample_expr(self, node: ast.SampleExpr):
        sample_value = self.visit_ratio_expr(node.sample_value)
        offset_clause = ""
        if node.offset_value:
            offset_value = self.visit_ratio_expr(node.offset_value)
            offset_clause = f" OFFSET {offset_value}"

        return f"SAMPLE {sample_value}{offset_clause}"

    def visit_ratio_expr(self, node: ast.RatioExpr):
        return self.visit(node.left) if node.right is None else f"{self.visit(node.left)}/{self.visit(node.right)}"

    def visit_select_query_alias_type(self, type: ast.SelectQueryAliasType):
        return self._print_identifier(type.alias)

    def visit_field_alias_type(self, type: ast.FieldAliasType):
        return self._print_identifier(type.alias)

    def visit_virtual_table_type(self, type: ast.VirtualTableType):
        return self.visit(type.table_type)

    def visit_asterisk_type(self, type: ast.AsteriskType):
        return "*"

    def visit_lazy_join_type(self, type: ast.LazyJoinType):
        raise HogQLException("Unexpected ast.LazyJoinType. Make sure LazyJoinResolver has run on the AST.")

    def visit_lazy_table_type(self, type: ast.LazyJoinType):
        raise HogQLException("Unexpected ast.LazyTableType. Make sure LazyJoinResolver has run on the AST.")

    def visit_field_traverser_type(self, type: ast.FieldTraverserType):
        raise HogQLException("Unexpected ast.FieldTraverserType. This should have been resolved.")

    def visit_unknown(self, node: AST):
        raise HogQLException(f"Unknown AST node {type(node).__name__}")

    def visit_window_expr(self, node: ast.WindowExpr):
        strings: List[str] = []
        if node.partition_by is not None:
            if len(node.partition_by) == 0:
                raise HogQLException("PARTITION BY must have at least one argument")
            strings.append("PARTITION BY")
            for expr in node.partition_by:
                strings.append(self.visit(expr))

        if node.order_by is not None:
            if len(node.order_by) == 0:
                raise HogQLException("ORDER BY must have at least one argument")
            strings.append("ORDER BY")
            for expr in node.order_by:
                strings.append(self.visit(expr))

        if node.frame_method is not None:
            if node.frame_method == "ROWS":
                strings.append("ROWS")
            elif node.frame_method == "RANGE":
                strings.append("RANGE")
            else:
                raise HogQLException(f"Invalid frame method {node.frame_method}")
            if node.frame_start and node.frame_end is None:
                strings.append(self.visit(node.frame_start))

            elif node.frame_start is not None and node.frame_end is not None:
                strings.append("BETWEEN")
                strings.append(self.visit(node.frame_start))
                strings.append("AND")
                strings.append(self.visit(node.frame_end))

            else:
                raise HogQLException("Frame start and end must be specified together")
        return " ".join(strings)

    def visit_window_function(self, node: ast.WindowFunction):
        over = f"({self.visit(node.over_expr)})" if node.over_expr else self._print_identifier(node.over_identifier)
        return f"{self._print_identifier(node.name)}({', '.join(self.visit(expr) for expr in node.args or [])}) OVER {over}"

    def visit_window_frame_expr(self, node: ast.WindowFrameExpr):
        if node.frame_type == "PRECEDING":
            return f"{int(str(node.frame_value)) if node.frame_value is not None else 'UNBOUNDED'} PRECEDING"
        elif node.frame_type == "FOLLOWING":
            return f"{int(str(node.frame_value)) if node.frame_value is not None else 'UNBOUNDED'} FOLLOWING"
        elif node.frame_type == "CURRENT ROW":
            return "CURRENT ROW"
        else:
            raise HogQLException(f"Invalid frame type {node.frame_type}")

    def _last_select(self) -> Optional[ast.SelectQuery]:
        """Find the last SELECT query in the stack."""
        for node in reversed(self.stack):
            if isinstance(node, ast.SelectQuery):
                return node
        return None

    def _print_identifier(self, name: str) -> str:
        if self.dialect == "clickhouse":
            return escape_clickhouse_identifier(name)
        return escape_hogql_identifier(name)

    def _print_hogql_identifier_or_index(self, name: str | int) -> str:
        # Regular identifiers can't start with a number. Print digit strings as-is for unescaped tuple access.
        if isinstance(name, int) and str(name).isdigit():
            return str(name)
        return escape_hogql_identifier(name)

    def _print_escaped_string(self, name: float | int | str | list | tuple | datetime | date) -> str:
        if self.dialect == "clickhouse":
            return escape_clickhouse_string(name, timezone=self._get_timezone())
        return escape_hogql_string(name, timezone=self._get_timezone())

    def _unsafe_json_extract_trim_quotes(self, unsafe_field: str, unsafe_args: List[str]) -> str:
        return f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw({', '.join([unsafe_field] + unsafe_args)}), ''), 'null'), '^\"|\"$', '')"

    def _get_materialized_column(
        self, table_name: str, property_name: PropertyName, field_name: TableColumn
    ) -> Optional[str]:
        try:
            from ee.clickhouse.materialized_columns.columns import (
                TablesWithMaterializedColumns,
                get_materialized_columns,
            )

            materialized_columns = get_materialized_columns(cast(TablesWithMaterializedColumns, table_name))
            return materialized_columns.get((property_name, field_name), None)
        except ModuleNotFoundError:
            return None

    def _get_timezone(self) -> str:
        return self.context.database.get_timezone() if self.context.database else "UTC"

    def _get_week_start_day(self) -> WeekStartDay:
        return self.context.database.get_week_start_day() if self.context.database else WeekStartDay.SUNDAY

    def _is_nullable(self, node: ast.Expr) -> bool:
        if isinstance(node, ast.Constant):
            return node.value is None
        elif isinstance(node.type, ast.PropertyType):
            return True
        elif isinstance(node.type, ast.FieldType):
            return node.type.is_nullable()

        # we don't know if it's nullable, so we assume it can be
        return True

    def _print_settings(self, settings):
        pairs = []
        for key, value in settings:
            if value is None:
                continue
            if not isinstance(value, (int, float, str)):
                raise HogQLException(f"Setting {key} must be a string, int, or float")
            if not re.match(r"^[a-zA-Z0-9_]+$", key):
                raise HogQLException(f"Setting {key} is not supported")
            if isinstance(value, bool):
                pairs.append(f"{key}={1 if value else 0}")
            elif isinstance(value, int) or isinstance(value, float):
                pairs.append(f"{key}={value}")
            else:
                pairs.append(f"{key}={self._print_escaped_string(value)}")
        if len(pairs) > 0:
            return f"SETTINGS {', '.join(pairs)}"
        return None
