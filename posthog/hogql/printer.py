import re
from dataclasses import dataclass
from datetime import datetime
from difflib import get_close_matches
from typing import List, Literal, Optional, Union, cast


from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.constants import (
    MAX_SELECT_RETURNED_ROWS,
    HogQLSettings,
)
from posthog.hogql.functions import (
    ADD_OR_NULL_DATETIME_FUNCTIONS,
    HOGQL_CLICKHOUSE_FUNCTIONS,
    FIRST_ARG_DATETIME_FUNCTIONS,
    HOGQL_AGGREGATIONS,
    ADD_TIMEZONE_TO_FUNCTIONS,
    HOGQL_POSTHOG_FUNCTIONS,
)
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import Table, FunctionCallTable
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.errors import HogQLException
from posthog.hogql.escape_sql import (
    escape_clickhouse_identifier,
    escape_clickhouse_string,
    escape_hogql_identifier,
    escape_hogql_string,
)
from posthog.hogql.functions.mapping import validate_function_args
from posthog.hogql.resolver import ResolverException, lookup_field_by_name, resolve_types
from posthog.hogql.transforms.lazy_tables import resolve_lazy_tables
from posthog.hogql.transforms.property_types import resolve_property_types
from posthog.hogql.visitor import Visitor
from posthog.models.property import PropertyName, TableColumn
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


def print_ast(
    node: ast.Expr,
    context: HogQLContext,
    dialect: Literal["hogql", "clickhouse"],
    stack: Optional[List[ast.SelectQuery]] = None,
    settings: Optional[HogQLSettings] = None,
) -> str:
    prepared_ast = prepare_ast_for_printing(node=node, context=context, dialect=dialect, stack=stack)
    return print_prepared_ast(node=prepared_ast, context=context, dialect=dialect, stack=stack, settings=settings)


def prepare_ast_for_printing(
    node: ast.Expr,
    context: HogQLContext,
    dialect: Literal["hogql", "clickhouse"],
    stack: Optional[List[ast.SelectQuery]] = None,
) -> ast.Expr:

    context.database = context.database or create_hogql_database(context.team_id)

    node = resolve_types(node, context, scopes=[node.type for node in stack] if stack else None)
    if dialect == "clickhouse":
        node = resolve_property_types(node, context)
        resolve_lazy_tables(node, stack, context)

    # We add a team_id guard right before printing. It's not a separate step here.
    return node


def print_prepared_ast(
    node: ast.Expr,
    context: HogQLContext,
    dialect: Literal["hogql", "clickhouse"],
    stack: Optional[List[ast.SelectQuery]] = None,
    settings: Optional[HogQLSettings] = None,
) -> str:
    # _Printer also adds a team_id guard if printing clickhouse
    return _Printer(context=context, dialect=dialect, stack=stack or [], settings=settings).visit(node)


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
        settings: Optional[HogQLSettings] = None,
    ):
        self.context = context
        self.dialect = dialect
        self.stack: List[AST] = stack or []  # Keep track of all traversed nodes.
        self.settings = settings

    def visit(self, node: AST):
        self.stack.append(node)
        response = super().visit(node)
        self.stack.pop()

        if len(self.stack) == 0 and self.dialect == "clickhouse" and self.settings:
            if not isinstance(node, ast.SelectQuery) and not isinstance(node, ast.SelectUnionQuery):
                raise HogQLException("Settings can only be applied to SELECT queries")
            settings = []
            for key, value in self.settings:
                if not isinstance(value, (int, float, str)):
                    raise HogQLException(f"Setting {key} must be a string, int, or float")
                if not re.match(r"^[a-zA-Z0-9_]+$", key):
                    raise HogQLException(f"Setting {key} is not supported")
                if isinstance(value, int) or isinstance(value, float):
                    settings.append(f"{key}={value}")
                else:
                    settings.append(f"{key}={self._print_escaped_string(value)}")
            if len(settings) > 0:
                response += f" SETTINGS {', '.join(settings)}"

        return response

    def visit_select_union_query(self, node: ast.SelectUnionQuery):
        query = " UNION ALL ".join([self.visit(expr) for expr in node.select_queries])
        if len(self.stack) > 1:
            return f"({query})"
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

        clauses = [
            f"SELECT {'DISTINCT ' if node.distinct else ''}{', '.join(columns)}",
            f"FROM {' '.join(joined_tables)}" if len(joined_tables) > 0 else None,
            "PREWHERE " + prewhere if prewhere else None,
            "WHERE " + where if where else None,
            f"GROUP BY {', '.join(group_by)}" if group_by and len(group_by) > 0 else None,
            "HAVING " + having if having else None,
            "WINDOW " + window if window else None,
            f"ORDER BY {', '.join(order_by)}" if order_by and len(order_by) > 0 else None,
        ]

        limit = node.limit
        if self.context.limit_top_select and is_top_level_query:
            if limit is not None:
                if isinstance(limit, ast.Constant) and isinstance(limit.value, int):
                    limit.value = min(limit.value, MAX_SELECT_RETURNED_ROWS)
                else:
                    limit = ast.Call(name="min2", args=[ast.Constant(value=MAX_SELECT_RETURNED_ROWS), limit])
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

        response = " ".join([clause for clause in clauses if clause])

        # If we are printing a SELECT subquery (not the first AST node we are visiting), wrap it in parentheses.
        if not part_of_select_union and not is_top_level_query:
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

            if not isinstance(table_type, ast.TableType):
                raise HogQLException(f"Invalid table type {type(table_type).__name__} in join_expr")

            # :IMPORTANT: This assures a "team_id" where clause is present on every selected table.
            # Skip function call tables like numbers(), s3(), etc.
            if self.dialect == "clickhouse" and not isinstance(table_type.table, FunctionCallTable):
                extra_where = team_id_guard_for_table(node.type, self.context)

            if self.dialect == "clickhouse":
                sql = table_type.table.to_printed_clickhouse(self.context)
            else:
                sql = table_type.table.to_printed_hogql()
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

        if node.op == ast.CompareOperationOp.Eq:
            if isinstance(node.left, ast.Constant) and isinstance(node.right, ast.Constant):
                return "1" if node.left.value == node.right.value else "0"
            elif in_join_constraint or self.dialect == "hogql" or not_nullable:
                return f"equals({left}, {right})"
            elif isinstance(node.right, ast.Constant):
                if node.right.value is None:
                    return f"isNull({left})"
                return f"ifNull(equals({left}, {right}), 0)"
            elif isinstance(node.left, ast.Constant):
                if node.left.value is None:
                    return f"isNull({right})"
                return f"ifNull(equals({left}, {right}), 0)"
            else:
                return f"ifNull(equals({left}, {right}), isNull({left}) and isNull({right}))"
        elif node.op == ast.CompareOperationOp.NotEq:
            if isinstance(node.left, ast.Constant) and isinstance(node.right, ast.Constant):
                return "1" if node.left.value != node.right.value else "0"
            elif in_join_constraint or self.dialect == "hogql" or not_nullable:
                return f"notEquals({left}, {right})"
            elif isinstance(node.right, ast.Constant):
                if node.right.value is None:
                    return f"isNotNull({left})"
                return f"ifNull(notEquals({left}, {right}), 1)"
            elif isinstance(node.left, ast.Constant):
                if node.left.value is None:
                    return f"isNotNull({right})"
                return f"ifNull(notEquals({left}, {right}), 1)"
            else:
                return f"ifNull(notEquals({left}, {right}), isNotNull({left}) or isNotNull({right}))"

        elif node.op == ast.CompareOperationOp.Gt:
            return f"greater({left}, {right})"
        elif node.op == ast.CompareOperationOp.GtEq:
            return f"greaterOrEquals({left}, {right})"
        elif node.op == ast.CompareOperationOp.Lt:
            return f"less({left}, {right})"
        elif node.op == ast.CompareOperationOp.LtEq:
            return f"lessOrEquals({left}, {right})"
        elif node.op == ast.CompareOperationOp.Like:
            return f"like({left}, {right})"
        elif node.op == ast.CompareOperationOp.NotLike:
            return f"notLike({left}, {right})"
        elif node.op == ast.CompareOperationOp.ILike:
            return f"ilike({left}, {right})"
        elif node.op == ast.CompareOperationOp.NotILike:
            return f"notILike({left}, {right})"
        elif node.op == ast.CompareOperationOp.In:
            return f"in({left}, {right})"
        elif node.op == ast.CompareOperationOp.NotIn:
            return f"notIn({left}, {right})"
        elif node.op == ast.CompareOperationOp.Regex:
            return f"match({left}, {right})"
        elif node.op == ast.CompareOperationOp.NotRegex:
            return f"not(match({left}, {right}))"
        elif node.op == ast.CompareOperationOp.IRegex:
            return f"match({left}, concat('(?i)', {right}))"
        elif node.op == ast.CompareOperationOp.NotIRegex:
            return f"not(match({left}, concat('(?i)', {right})))"
        else:
            raise HogQLException(f"Unknown CompareOperationOp: {type(node.op).__name__}")

    def visit_constant(self, node: ast.Constant):
        if self.dialect == "clickhouse" and (
            isinstance(node.value, str) or isinstance(node.value, list) or isinstance(node.value, tuple)
        ):
            # inline the string in hogql, but use %(hogql_val_0)s in clickhouse
            return self.context.add_value(node.value)
        else:
            return self._print_escaped_string(node.value)

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
                node.args, func_meta.min_args, func_meta.max_args, node.name, function_term="aggregation"
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
                    node.params, func_meta.min_params, func_meta.max_params, node.name, argument_term="parameter"
                )

            if self.dialect == "clickhouse":
                if node.name in FIRST_ARG_DATETIME_FUNCTIONS:
                    args: List[str] = []
                    for idx, arg in enumerate(node.args):
                        if idx == 0:
                            if isinstance(arg, ast.Call) and arg.name in ADD_OR_NULL_DATETIME_FUNCTIONS:
                                args.append(f"assumeNotNull(toDateTime({self.visit(arg)}))")
                            else:
                                args.append(f"toDateTime({self.visit(arg)})")
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

                if (func_meta.clickhouse_name == "now64" and len(node.args) == 0) or (
                    func_meta.clickhouse_name == "parseDateTime64BestEffortOrNull" and len(node.args) == 1
                ):
                    # must add precision if adding timezone in the next step
                    args.append("6")

                if node.name in ADD_TIMEZONE_TO_FUNCTIONS:
                    args.append(self.visit(ast.Constant(value=self._get_timezone())))

                params = [self.visit(param) for param in node.params] if node.params is not None else None

                params_part = f"({', '.join(params)})" if params is not None else ""
                args_part = f"({', '.join(args)})"
                return f"{func_meta.clickhouse_name}{params_part}{args_part}"
            else:
                return f"{node.name}({', '.join([self.visit(arg) for arg in node.args])})"
        elif node.name in HOGQL_POSTHOG_FUNCTIONS:
            raise HogQLException(f"Unexpected unresolved HogQL function '{node.name}(...)'")
        else:
            all_function_names = list(HOGQL_CLICKHOUSE_FUNCTIONS.keys()) + list(HOGQL_AGGREGATIONS.keys())
            close_matches = get_close_matches(node.name, all_function_names, 1)
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
        if "%" in alias:
            raise HogQLException(f"Alias \"{node.alias}\" contains unsupported character '%'")
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
                                table_type=ast.TableType(table=resolved_field), alias=type.table_type.alias
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
                if self.context.person_on_events_mode != PersonOnEventsMode.DISABLED:
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
                if self.context.person_on_events_mode != PersonOnEventsMode.DISABLED:
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
            if self.context.person_on_events_mode != PersonOnEventsMode.DISABLED:
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
        # Regular identifiers can't start with a number. Print digit strings as-is for unesacped tuple access.
        if isinstance(name, int) and str(name).isdigit():
            return str(name)
        return escape_hogql_identifier(name)

    def _print_escaped_string(self, name: float | int | str | list | tuple | datetime) -> str:
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

    def _get_timezone(self):
        return self.context.database.get_timezone() if self.context.database else "UTC"

    def _is_nullable(self, node: ast.Expr) -> bool:
        if isinstance(node, ast.Constant):
            return node.value is None
        elif isinstance(node.type, ast.PropertyType):
            return True
        elif isinstance(node.type, ast.FieldType):
            return node.type.is_nullable()
        # we don't know if it's nullable, so we assume it can be
        return True
