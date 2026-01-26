from collections.abc import Iterable
from datetime import date, datetime
from difflib import get_close_matches
from typing import Any, Optional, cast
from uuid import UUID

from posthog.schema import PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.ast import StringType
from posthog.hogql.base import AST
from posthog.hogql.constants import HogQLDialect, HogQLGlobalSettings, LimitContext, get_max_limit_for_context
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import FunctionCallTable, Table
from posthog.hogql.errors import ImpossibleASTError, QueryError, ResolutionError
from posthog.hogql.escape_sql import escape_hogql_identifier, escape_hogql_string
from posthog.hogql.functions import (
    HogQLFunctionMeta,
    find_hogql_aggregation,
    find_hogql_function,
    find_hogql_posthog_function,
)
from posthog.hogql.functions.core import validate_function_args
from posthog.hogql.functions.mapping import (
    ALL_EXPOSED_FUNCTION_NAMES,
    HOGQL_COMPARISON_MAPPING,
    is_allowed_parametric_function,
)
from posthog.hogql.printer.types import JoinExprResponse
from posthog.hogql.resolver_utils import lookup_field_by_name
from posthog.hogql.visitor import Visitor, clone_expr

from posthog.models.utils import UUIDT


def resolve_field_type(expr: ast.Expr) -> ast.Type | None:
    expr_type = expr.type
    while isinstance(expr_type, ast.FieldAliasType):
        expr_type = expr_type.type
    return expr_type


class HogQLPrinter(Visitor[str]):
    # NOTE: Call "print_ast()", not this class directly.

    def __init__(
        self,
        context: HogQLContext,
        dialect: HogQLDialect,
        stack: list[AST] | None = None,
        settings: HogQLGlobalSettings | None = None,
        pretty: bool = False,
    ):
        self.context = context
        self.dialect = dialect
        self.stack: list[AST] = stack or []  # Keep track of all traversed nodes.
        self.settings = settings
        self.pretty = pretty
        self._indent = -1
        self.tab_size = 4

    def indent(self, extra: int = 0):
        return " " * self.tab_size * (self._indent + extra)

    def visit(self, node: AST | None):
        if node is None:
            return ""
        self.stack.append(node)
        self._indent += 1
        response = super().visit(node)
        self._indent -= 1
        self.stack.pop()

        return response

    def visit_select_set_query(self, node: ast.SelectSetQuery):
        self._indent -= 1
        ret = self.visit(node.initial_select_query)
        if self.pretty:
            ret = ret.strip()
        for expr in node.subsequent_select_queries:
            query = self.visit(expr.select_query)
            if self.pretty:
                query = query.strip()
            if expr.set_operator is not None:
                if self.pretty:
                    ret += f"\n{self.indent(1)}{expr.set_operator}\n{self.indent(1)}"
                else:
                    ret += f" {expr.set_operator} "
            ret += query
        self._indent += 1
        if len(self.stack) > 1:
            return f"({ret.strip()})"
        return ret

    def _print_select_columns(self, columns: Iterable[ast.Expr]) -> list[str]:
        return [self.visit(column) for column in columns]

    def visit_select_query(self, node: ast.SelectQuery):
        # if we are the first parsed node in the tree, or a child of a SelectSetQuery, mark us as a top level query
        part_of_select_union = len(self.stack) >= 2 and isinstance(self.stack[-2], ast.SelectSetQuery)
        is_top_level_query = len(self.stack) <= 1 or (len(self.stack) == 2 and part_of_select_union)
        is_last_query_in_union = (
            part_of_select_union
            and isinstance(self.stack[0], ast.SelectSetQuery)
            and len(self.stack[0].subsequent_select_queries) > 0
            and self.stack[0].subsequent_select_queries[-1].select_query is node
        )

        # We will add extra clauses onto this from the joined tables
        where = node.where

        joined_tables = []
        next_join = node.select_from
        while isinstance(next_join, ast.JoinExpr):
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
                    where = ast.And(exprs=[extra_where, *where.exprs])
                else:
                    where = ast.And(exprs=[extra_where, where])
            else:
                raise ImpossibleASTError(
                    f"Invalid where of type {type(extra_where).__name__} returned by join_expr", node=visited_join.where
                )

            next_join = next_join.next_join

        if node.select:
            columns = self._print_select_columns(node.select)
        else:
            columns = ["1"]

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
                raise ImpossibleASTError(f"Invalid ARRAY JOIN operation: {node.array_join_op}")
            array_join = node.array_join_op
            if node.array_join_list is None or len(node.array_join_list or []) == 0:
                raise ImpossibleASTError(f"Invalid ARRAY JOIN without an array")
            array_join += f" {', '.join(self.visit(expr) for expr in node.array_join_list)}"

        space = f"\n{self.indent(1)}" if self.pretty else " "
        comma = f",\n{self.indent(1)}" if self.pretty else ", "

        clauses = [
            f"SELECT{space}{'DISTINCT ' if node.distinct else ''}{comma.join(columns)}",
            f"FROM{space}{space.join(joined_tables)}" if len(joined_tables) > 0 else None,
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
            max_limit = get_max_limit_for_context(self.context.limit_context or LimitContext.QUERY)

            if limit is not None:
                if isinstance(limit, ast.Constant) and isinstance(limit.value, int):
                    limit.value = min(limit.value, max_limit)
                else:
                    limit = ast.Call(
                        name="min2",
                        args=[ast.Constant(value=max_limit), limit],
                    )
            else:
                limit = ast.Constant(value=max_limit)

        if node.limit_by is not None:
            clauses.append(
                f"LIMIT {self.visit(node.limit_by.n)} {f'OFFSET {self.visit(node.limit_by.offset_value)}' if node.limit_by.offset_value else ''} BY {', '.join([self.visit(expr) for expr in node.limit_by.exprs])}"
            )

        if limit is not None:
            clauses.append(f"LIMIT {self.visit(limit)}")
            if node.limit_with_ties:
                clauses.append("WITH TIES")

        if node.offset is not None:
            clauses.append(f"OFFSET {self.visit(node.offset)}")

        clauses.extend(
            self._get_extra_select_clauses(
                node, is_top_level_query, part_of_select_union, is_last_query_in_union, space
            )
        )

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

    def _get_extra_select_clauses(
        self,
        node: ast.SelectQuery,
        is_top_level_query: bool,
        part_of_select_union: bool,
        is_last_query_in_union: bool,
        space: str,
    ) -> list[str]:
        return []

    def _ensure_team_id_where_clause(
        self,
        table_type: ast.TableType | ast.LazyTableType,
        node_type: ast.TableOrSelectType,
    ):
        if self.dialect != "hogql":
            raise NotImplementedError("HogQLPrinter._ensure_team_id_where_clause not overridden")

    def _print_table_ref(self, table_type: ast.TableType | ast.LazyTableType, node: ast.JoinExpr) -> str:
        if self.dialect == "hogql":
            return table_type.table.to_printed_hogql()
        raise ImpossibleASTError(f"Unsupported dialect {self.dialect}")

    def visit_join_expr(self, node: ast.JoinExpr) -> JoinExprResponse:
        # Constraints to add to the SELECT's WHERE clause (for most join types)
        extra_where: ast.Expr | None = None
        # For LEFT JOINs, team_id goes in ON instead of WHERE to preserve NULL rows
        team_id_for_on_clause: ast.Expr | None = None

        join_strings = []

        if node.join_type is not None:
            join_strings.append(node.join_type)

        if isinstance(node.type, ast.TableAliasType) or isinstance(node.type, ast.TableType):
            table_type: ast.TableType | ast.LazyTableType | ast.TableAliasType = node.type
            while isinstance(table_type, ast.TableAliasType):
                table_type = cast(ast.TableType | ast.LazyTableType | ast.TableAliasType, table_type.table_type)

            if not isinstance(table_type, ast.TableType) and not isinstance(table_type, ast.LazyTableType):
                raise ImpossibleASTError(f"Invalid table type {type(table_type).__name__} in join_expr")

            # :IMPORTANT: Ensures team_id filtering on every table. For LEFT JOINs, we add it to the
            # ON clause (not WHERE) to preserve LEFT JOIN semantics - otherwise NULL rows get filtered out.
            team_id_expr = self._ensure_team_id_where_clause(table_type, node.type)
            is_left_join = node.join_type is not None and "LEFT" in node.join_type
            if is_left_join and team_id_expr is not None and node.constraint is not None:
                team_id_for_on_clause = team_id_expr
            else:
                extra_where = team_id_expr

            sql = self._print_table_ref(table_type, node)

            if isinstance(table_type.table, FunctionCallTable) and table_type.table.requires_args:
                if node.table_args is None:
                    raise QueryError(f"Table function '{table_type.table.name}' requires arguments")

                if table_type.table.min_args is not None and (
                    node.table_args is None or len(node.table_args) < table_type.table.min_args
                ):
                    raise QueryError(
                        f"Table function '{table_type.table.name}' requires at least {table_type.table.min_args} argument{'s' if table_type.table.min_args > 1 else ''}"
                    )
                if table_type.table.max_args is not None and (
                    node.table_args is None or len(node.table_args) > table_type.table.max_args
                ):
                    raise QueryError(
                        f"Table function '{table_type.table.name}' requires at most {table_type.table.max_args} argument{'s' if table_type.table.max_args > 1 else ''}"
                    )
                if node.table_args is not None and len(node.table_args) > 0:
                    sql = f"{sql}({', '.join([self.visit(arg) for arg in node.table_args])})"
            elif node.table_args is not None:
                raise QueryError(f"Table '{table_type.table.to_printed_hogql()}' does not accept arguments")

            join_strings.append(sql)

            if isinstance(node.type, ast.TableAliasType) and node.alias is not None and node.alias != sql:
                join_strings.append(f"AS {self._print_identifier(node.alias)}")

        elif isinstance(node.type, ast.SelectQueryType):
            join_strings.append(self.visit(node.table))

        elif isinstance(node.type, ast.SelectSetQueryType):
            join_strings.append(self.visit(node.table))

        elif isinstance(node.type, ast.SelectViewType) and node.alias is not None:
            join_strings.append(self.visit(node.table))
            join_strings.append(f"AS {self._print_identifier(node.alias)}")

        elif isinstance(node.type, ast.SelectQueryAliasType) and node.alias is not None:
            join_strings.append(self.visit(node.table))
            join_strings.append(f"AS {self._print_identifier(node.alias)}")

        elif isinstance(node.type, ast.LazyTableType):
            if self.dialect == "hogql":
                join_strings.append(self._print_identifier(node.type.table.to_printed_hogql()))
            else:
                raise ImpossibleASTError(f"Unexpected LazyTableType for: {node.type.table.to_printed_hogql()}")

        elif self.dialect == "hogql":
            join_strings.append(self.visit(node.table))
            if node.alias is not None:
                join_strings.append(f"AS {self._print_identifier(node.alias)}")
        else:
            raise QueryError(
                f"Only selecting from a table or a subquery is supported. Unexpected type: {node.type.__class__.__name__}"
            )

        if node.table_final:
            raise QueryError("The FINAL keyword is not supported in HogQL as it causes slow queries")

        if node.sample is not None:
            sample_clause = self.visit_sample_expr(node.sample)
            if sample_clause is not None:
                join_strings.append(sample_clause)

        if node.constraint is not None:
            if team_id_for_on_clause is not None:
                combined_constraint = ast.And(exprs=[team_id_for_on_clause, node.constraint.expr])
                join_strings.append(f"{node.constraint.constraint_type} {self.visit(combined_constraint)}")
            else:
                join_strings.append(f"{node.constraint.constraint_type} {self.visit(node.constraint)}")

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
            raise ImpossibleASTError(f"Unknown ArithmeticOperationOp {node.op}")

    def visit_and(self, node: ast.And):
        if len(node.exprs) == 1:
            return self.visit(node.exprs[0])

        return f"and({', '.join([self.visit(expr) for expr in node.exprs])})"

    def visit_or(self, node: ast.Or):
        if len(node.exprs) == 1:
            return self.visit(node.exprs[0])

        return f"or({', '.join([self.visit(expr) for expr in node.exprs])})"

    def visit_not(self, node: ast.Not):
        return f"not({self.visit(node.expr)})"

    def visit_tuple_access(self, node: ast.TupleAccess):
        visited_tuple = self.visit(node.tuple)
        visited_index = int(str(node.index))
        symbol = "?." if self.dialect == "hogql" and node.nullish else "."
        if isinstance(node.tuple, ast.Field) or isinstance(node.tuple, ast.Tuple) or isinstance(node.tuple, ast.Call):
            return f"{visited_tuple}{symbol}{visited_index}"
        return f"({visited_tuple}){symbol}{visited_index}"

    def visit_tuple(self, node: ast.Tuple):
        return f"tuple({', '.join([self.visit(expr) for expr in node.exprs])})"

    def visit_array_access(self, node: ast.ArrayAccess):
        symbol = "?." if self.dialect == "hogql" and node.nullish else ""
        return f"{self.visit(node.array)}{symbol}[{self.visit(node.property)}]"

    def visit_array(self, node: ast.Array):
        return f"[{', '.join([self.visit(expr) for expr in node.exprs])}]"

    def _get_tuple_function(self) -> str:
        return "tuple"

    def visit_dict(self, node: ast.Dict):
        str = f"{self._get_tuple_function()}('__hx_tag', '__hx_obj'"
        for key, value in node.items:
            str += f", {self.visit(key)}, {self.visit(value)}"
        return str + ")"

    def visit_lambda(self, node: ast.Lambda):
        identifiers = [self._print_identifier(arg) for arg in node.args]
        if len(identifiers) == 0:
            raise ValueError("Lambdas require at least one argument")
        elif len(identifiers) == 1:
            return f"{identifiers[0]} -> {self.visit(node.expr)}"
        return f"({', '.join(identifiers)}) -> {self.visit(node.expr)}"

    def visit_order_expr(self, node: ast.OrderExpr):
        return f"{self.visit(node.expr)} {node.order}"

    def _get_compare_op(self, op: ast.CompareOperationOp, left: str, right: str) -> str:
        if op == ast.CompareOperationOp.Eq:
            return f"equals({left}, {right})"
        elif op == ast.CompareOperationOp.NotEq:
            return f"notEquals({left}, {right})"
        elif op == ast.CompareOperationOp.Like:
            return f"like({left}, {right})"
        elif op == ast.CompareOperationOp.NotLike:
            return f"notLike({left}, {right})"
        elif op == ast.CompareOperationOp.ILike:
            return f"ilike({left}, {right})"
        elif op == ast.CompareOperationOp.NotILike:
            return f"notILike({left}, {right})"
        elif op == ast.CompareOperationOp.In:
            return f"in({left}, {right})"
        elif op == ast.CompareOperationOp.NotIn:
            return f"notIn({left}, {right})"
        elif op == ast.CompareOperationOp.GlobalIn:
            return f"globalIn({left}, {right})"
        elif op == ast.CompareOperationOp.GlobalNotIn:
            return f"globalNotIn({left}, {right})"
        elif op == ast.CompareOperationOp.Regex:
            return f"match({left}, {right})"
        elif op == ast.CompareOperationOp.NotRegex:
            return f"not(match({left}, {right}))"
        elif op == ast.CompareOperationOp.IRegex:
            return f"match({left}, concat('(?i)', {right}))"
        elif op == ast.CompareOperationOp.NotIRegex:
            return f"not(match({left}, concat('(?i)', {right})))"
        elif op == ast.CompareOperationOp.Gt:
            return f"greater({left}, {right})"
        elif op == ast.CompareOperationOp.GtEq:
            return f"greaterOrEquals({left}, {right})"
        elif op == ast.CompareOperationOp.Lt:
            return f"less({left}, {right})"
        elif op == ast.CompareOperationOp.LtEq:
            return f"lessOrEquals({left}, {right})"
        # only used for hogql direct printing (no prepare called)
        elif op == ast.CompareOperationOp.InCohort and self.dialect == "hogql":
            return f"{left} IN COHORT {right}"
        # only used for hogql direct printing (no prepare called)
        elif op == ast.CompareOperationOp.NotInCohort and self.dialect == "hogql":
            return f"{left} NOT IN COHORT {right}"
        else:
            raise ImpossibleASTError(f"Unknown CompareOperationOp: {op.name}")

    def visit_compare_operation(self, node: ast.CompareOperation):
        left = self.visit(node.left)
        right = self.visit(node.right)
        return self._get_compare_op(node.op, left, right)

    def visit_between_expr(self, node: ast.BetweenExpr):
        expr = self.visit(node.expr)
        low = self.visit(node.low)
        high = self.visit(node.high)
        not_kw = " NOT" if node.negated else ""
        op = f"{expr}{not_kw} BETWEEN {low} AND {high}"

        return op

    def visit_constant(self, node: ast.Constant):
        # Inline everything in HogQL
        return self._print_escaped_string(node.value)

    def visit_field(self, node: ast.Field):
        if node.chain == ["*"]:
            return "*"
        # When printing HogQL, we print the properties out as a chain as they are.
        return ".".join([self._print_hogql_identifier_or_index(identifier) for identifier in node.chain])

    def _validate_parametric_arguments(self, node: ast.Call, func_meta: HogQLFunctionMeta) -> str | None:
        if func_meta.parametric_first_arg:
            if not node.args:
                raise QueryError(f"Missing arguments in function '{node.name}'")
            # Check that the first argument is a constant string
            first_arg = node.args[0]
            if not isinstance(first_arg, ast.Constant):
                raise QueryError(
                    f"Expected constant string as first arg in function '{node.name}', got {first_arg.__class__.__name__}"
                )
            if not isinstance(first_arg.type, StringType) or not isinstance(first_arg.value, str):
                raise QueryError(
                    f"Expected constant string as first arg in function '{node.name}', got {first_arg.type.__class__.__name__} '{first_arg.value}'"
                )
            # Check that the constant string is within our allowed set of functions
            if not is_allowed_parametric_function(first_arg.value):
                raise QueryError(f"Invalid parametric function in '{node.name}', '{first_arg.value}' is not supported.")

        return None

    def _validate_aggregation(self, node: ast.Call, func_meta: HogQLFunctionMeta):
        validate_function_args(
            node.args,
            func_meta.min_args,
            func_meta.max_args,
            node.name,
            function_term="aggregation",
        )
        if func_meta.min_params:
            if node.params is None:
                raise QueryError(f"Aggregation '{node.name}' requires parameters in addition to arguments")
            validate_function_args(
                node.params,
                func_meta.min_params,
                func_meta.max_params,
                node.name,
                function_term="aggregation",
                argument_term="parameter",
            )

        # check that we're not running inside another aggregate
        for stack_node in reversed(self.stack):
            if isinstance(stack_node, ast.SelectQuery):
                break
            if stack_node != node and isinstance(stack_node, ast.Call) and find_hogql_aggregation(stack_node.name):
                raise QueryError(
                    f"Aggregation '{node.name}' cannot be nested inside another aggregation '{stack_node.name}'."
                )

    def _print_aggregation_call(self, node: ast.Call, func_meta: HogQLFunctionMeta) -> str:
        arg_strings = [self.visit(arg) for arg in node.args]
        params = [self.visit(param) for param in node.params] if node.params is not None else None

        params_part = f"({', '.join(params)})" if params is not None else ""
        args_part = f"({f'DISTINCT ' if node.distinct else ''}{', '.join(arg_strings)})"

        return f"{node.name}{params_part}{args_part}"

    def _validate_hogql_function_call(self, node: ast.Call, func_meta: HogQLFunctionMeta):
        validate_function_args(
            node.args,
            func_meta.min_args,
            func_meta.max_args,
            node.name,
        )

        if func_meta.min_params:
            if node.params is None:
                raise QueryError(f"Function '{node.name}' requires parameters in addition to arguments")
            validate_function_args(
                node.params,
                func_meta.min_params,
                func_meta.max_params,
                node.name,
                argument_term="parameter",
            )

    def _print_hogql_function_call(self, node: ast.Call, func_meta: HogQLFunctionMeta) -> str:
        return f"{node.name}({', '.join([self.visit(arg) for arg in node.args])})"

    def _print_hogql_posthog_function_call(self, node: ast.Call, func_meta: HogQLFunctionMeta) -> str:
        args = [self.visit(arg) for arg in node.args]
        return f"{node.name}({', '.join(args)})"

    def visit_call(self, node: ast.Call):
        func_meta = (
            find_hogql_aggregation(node.name)
            or find_hogql_function(node.name)
            or find_hogql_posthog_function(node.name)
        )

        if func_meta and (parametric_result := self._validate_parametric_arguments(node, func_meta)):
            return parametric_result

        if node.name in HOGQL_COMPARISON_MAPPING:
            op = HOGQL_COMPARISON_MAPPING[node.name]
            if len(node.args) != 2:
                raise QueryError(f"Comparison '{node.name}' requires exactly two arguments")
            # We do "cleverer" logic with nullable types in visit_compare_operation
            return self.visit_compare_operation(
                ast.CompareOperation(
                    left=node.args[0],
                    right=node.args[1],
                    op=op,
                )
            )

        elif func_meta := find_hogql_aggregation(node.name):
            self._validate_aggregation(node, func_meta)
            return self._print_aggregation_call(node, func_meta)

        elif func_meta := find_hogql_function(node.name):
            self._validate_hogql_function_call(node, func_meta)
            return self._print_hogql_function_call(node, func_meta)

        elif func_meta := find_hogql_posthog_function(node.name):
            validate_function_args(
                node.args,
                func_meta.min_args,
                func_meta.max_args,
                node.name,
            )
            return self._print_hogql_posthog_function_call(node, func_meta)

        else:
            close_matches = get_close_matches(node.name, ALL_EXPOSED_FUNCTION_NAMES, 1)
            if len(close_matches) > 0:
                raise QueryError(
                    f"Unsupported function call '{node.name}(...)'. Perhaps you meant '{close_matches[0]}(...)'?"
                )
            raise QueryError(f"Unsupported function call '{node.name}(...)'")

    def visit_placeholder(self, node: ast.Placeholder):
        if node.field is None:
            raise QueryError("You can not use placeholders here")
        raise QueryError(f"Unresolved placeholder: {{{node.field}}}")

    def visit_alias(self, node: ast.Alias):
        # Skip hidden aliases completely.
        if node.hidden:
            return self.visit(node.expr)
        expr = node.expr
        while isinstance(expr, ast.Alias) and expr.hidden:
            expr = expr.expr
        inside = self.visit(expr)
        if isinstance(expr, ast.Alias):
            inside = f"({inside})"
        alias = self._print_identifier(node.alias)
        return f"{inside} AS {alias}"

    def visit_table_type(self, type: ast.TableType):
        return type.table.to_printed_hogql()

    def visit_table_alias_type(self, type: ast.TableAliasType):
        return self._print_identifier(type.alias)

    def visit_lambda_argument_type(self, type: ast.LambdaArgumentType):
        return self._print_identifier(type.name)

    def visit_field_type(self, type: ast.FieldType):
        try:
            last_select = self._last_select()
            type_with_name_in_scope = (
                lookup_field_by_name(last_select.type, type.name, self.context)
                if last_select and last_select.type
                else None
            )
        except ResolutionError:
            type_with_name_in_scope = None

        if (
            isinstance(type.table_type, ast.TableType)
            or isinstance(type.table_type, ast.TableAliasType)
            or isinstance(type.table_type, ast.VirtualTableType)
        ):
            resolved_field = type.resolve_database_field(self.context)
            if resolved_field is None:
                raise QueryError(f'Can\'t resolve field "{type.name}" on table.')

            if isinstance(resolved_field, Table):
                if isinstance(type.table_type, ast.VirtualTableType):
                    return self.visit(ast.AsteriskType(table_type=ast.TableType(table=resolved_field)))
                else:
                    return self.visit(
                        ast.AsteriskType(
                            table_type=ast.TableAliasType(
                                table_type=ast.TableType(table=resolved_field),
                                alias=cast(ast.Alias, type.table_type).alias,
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
                if self.context.modifiers.personsOnEventsMode != PersonsOnEventsMode.DISABLED:
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

        elif (
            isinstance(type.table_type, ast.SelectQueryType)
            or isinstance(type.table_type, ast.SelectQueryAliasType)
            or isinstance(type.table_type, ast.SelectViewType)
            or isinstance(type.table_type, ast.SelectSetQueryType)
        ):
            field_sql = self._print_identifier(type.name)
            if isinstance(type.table_type, ast.SelectQueryAliasType) or isinstance(type.table_type, ast.SelectViewType):
                field_sql = f"{self.visit(type.table_type)}.{field_sql}"

            # :KLUDGE: Legacy person properties handling. Only used within non-HogQL queries, such as insights.
            if self.context.within_non_hogql_query and field_sql == "events__pdi__person.properties":
                if self.context.modifiers.personsOnEventsMode != PersonsOnEventsMode.DISABLED:
                    field_sql = "person_properties"
                else:
                    field_sql = "person_props"

        else:
            error = f"Can't access field '{type.name}' on a table with type '{type.table_type.__class__.__name__}'."
            if isinstance(type.table_type, ast.LazyJoinType):
                error += f" Lazy joins should have all been replaced in the resolver."
            raise ImpossibleASTError(error)

        return field_sql

    def _print_property_type(self, type: ast.PropertyType) -> str:
        return self._unsafe_json_extract_trim_quotes(self.visit(type.field_type), self._json_property_args(type.chain))

    def visit_property_type(self, type: ast.PropertyType):
        if type.joined_subquery is not None and type.joined_subquery_field_name is not None:
            return f"{self._print_identifier(type.joined_subquery.alias)}.{self._print_identifier(type.joined_subquery_field_name)}"
        return self._print_property_type(type)

    def visit_sample_expr(self, node: ast.SampleExpr) -> Optional[str]:
        # SAMPLE 1 means no sampling, skip it entirely
        if node.sample_value.left.value == 1 and node.sample_value.right is None and node.offset_value is None:
            return None

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

    def visit_select_view_type(self, type: ast.SelectViewType):
        return self._print_identifier(type.alias)

    def visit_field_alias_type(self, type: ast.FieldAliasType):
        return self._print_identifier(type.alias)

    def visit_virtual_table_type(self, type: ast.VirtualTableType):
        return self.visit(type.table_type)

    def visit_asterisk_type(self, type: ast.AsteriskType):
        return "*"

    def visit_lazy_join_type(self, type: ast.LazyJoinType):
        raise ImpossibleASTError("Unexpected ast.LazyJoinType. Make sure LazyJoinResolver has run on the AST.")

    def visit_lazy_table_type(self, type: ast.LazyJoinType):
        raise ImpossibleASTError("Unexpected ast.LazyTableType. Make sure LazyJoinResolver has run on the AST.")

    def visit_field_traverser_type(self, type: ast.FieldTraverserType):
        raise ImpossibleASTError("Unexpected ast.FieldTraverserType. This should have been resolved.")

    def visit_unresolved_field_type(self, type: ast.UnresolvedFieldType):
        return self._print_identifier(type.name)

    def visit_unknown(self, node: AST):
        raise ImpossibleASTError(f"Unknown AST node {type(node).__name__}")

    def visit_window_expr(self, node: ast.WindowExpr):
        strings: list[str] = []
        if node.partition_by is not None:
            if len(node.partition_by) == 0:
                raise ImpossibleASTError("PARTITION BY must have at least one argument")
            strings.append("PARTITION BY")
            columns = []
            for expr in node.partition_by:
                columns.append(self.visit(expr))
            strings.append(", ".join(columns))

        if node.order_by is not None:
            if len(node.order_by) == 0:
                raise ImpossibleASTError("ORDER BY must have at least one argument")
            strings.append("ORDER BY")
            columns = []
            for expr in node.order_by:
                columns.append(self.visit(expr))
            strings.append(", ".join(columns))

        if node.frame_method is not None:
            if node.frame_method == "ROWS":
                strings.append("ROWS")
            elif node.frame_method == "RANGE":
                strings.append("RANGE")
            else:
                raise ImpossibleASTError(f"Invalid frame method {node.frame_method}")
            if node.frame_start and node.frame_end is None:
                strings.append(self.visit(node.frame_start))
            elif node.frame_start is not None and node.frame_end is not None:
                strings.append("BETWEEN")
                strings.append(self.visit(node.frame_start))
                strings.append("AND")
                strings.append(self.visit(node.frame_end))
            else:
                raise ImpossibleASTError("Frame start and end must be specified together")
        return " ".join(strings)

    def _transform_window_function(self, node: ast.WindowFunction) -> tuple[str, list[str], ast.WindowFunction]:
        identifier = self._print_identifier(node.name)
        exprs = [self.visit(expr) for expr in node.exprs or []]
        cloned_node = cast(ast.WindowFunction, clone_expr(node))
        return identifier, exprs, cloned_node

    def visit_window_function(self, node: ast.WindowFunction):
        identifier, exprs, cloned_node = self._transform_window_function(node)

        # Handle any additional function arguments
        args = f"({', '.join(self.visit(arg) for arg in cloned_node.args)})" if cloned_node.args else ""

        if cloned_node.over_expr:
            over = f"({self.visit(cloned_node.over_expr)})"
        elif cloned_node.over_identifier:
            over = self._print_identifier(cloned_node.over_identifier)
        else:
            over = "()"

        # Handle the case where we have both regular expressions and function arguments
        if cloned_node.args:
            return f"{identifier}({', '.join(exprs)}){args} OVER {over}"
        else:
            return f"{identifier}({', '.join(exprs)}) OVER {over}"

    def visit_window_frame_expr(self, node: ast.WindowFrameExpr):
        if node.frame_type == "PRECEDING":
            return f"{int(str(node.frame_value)) if node.frame_value is not None else 'UNBOUNDED'} PRECEDING"
        elif node.frame_type == "FOLLOWING":
            return f"{int(str(node.frame_value)) if node.frame_value is not None else 'UNBOUNDED'} FOLLOWING"
        elif node.frame_type == "CURRENT ROW":
            return "CURRENT ROW"
        else:
            raise ImpossibleASTError(f"Invalid frame type {node.frame_type}")

    def visit_hogqlx_tag(self, node: ast.HogQLXTag):
        attributes = []
        children = []
        for attribute in node.attributes:
            if isinstance(attribute, ast.HogQLXAttribute) and attribute.name == "children":
                if isinstance(attribute.value, list):
                    children.extend(attribute.value)
                else:
                    children.append(attribute.value)
            else:
                attributes.append(attribute)

        tag = f"<{self._print_identifier(node.kind)}"
        if attributes:
            tag += " " + (" ".join(self.visit(a) for a in attributes))
        if children:
            children_contents = [
                self.visit(child) if isinstance(child, ast.HogQLXTag) else "{" + self.visit(child) + "}"
                for child in children
            ]
            tag += ">" + ("".join(children_contents)) + "</" + self._print_identifier(node.kind) + ">"
        else:
            tag += " />"

        return tag

    def visit_hogqlx_attribute(self, node: ast.HogQLXAttribute):
        if isinstance(node.value, ast.HogQLXTag):
            value = self.visit(node.value)
        elif isinstance(node.value, list):
            value = "{[" + (", ".join(self.visit(x) for x in node.value)) + "]}"
        else:
            value = "{" + self.visit(node.value) + "}"
        return f"{self._print_identifier(node.name)}={value}"

    def _last_select(self) -> ast.SelectQuery | None:
        """Find the last SELECT query in the stack."""
        for node in reversed(self.stack):
            if isinstance(node, ast.SelectQuery):
                return node
        return None

    def _print_identifier(self, name: str) -> str:
        return escape_hogql_identifier(name)

    def _print_hogql_identifier_or_index(self, name: str | int) -> str:
        # Regular identifiers can't start with a number. Print digit strings as-is for unescaped tuple access.
        if isinstance(name, int) and str(name).isdigit():
            return str(name)
        return escape_hogql_identifier(name)

    def _print_escaped_string(self, name: float | int | str | list | tuple | datetime | date | UUID | UUIDT) -> str:
        return escape_hogql_string(name, timezone=self._get_timezone())

    def _unsafe_json_extract_trim_quotes(self, unsafe_field: str, unsafe_args: list[str]) -> str:
        return f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw({', '.join([unsafe_field, *unsafe_args])}), ''), 'null'), '^\"|\"$', '')"

    def _json_property_args(self, chain: Iterable[Any]) -> list[str]:
        return [self.context.add_value(name) for name in chain]

    def _get_timezone(self) -> str:
        if self.context.modifiers.convertToProjectTimezone is False:
            return "UTC"
        return self.context.database.get_timezone() if self.context.database else "UTC"
