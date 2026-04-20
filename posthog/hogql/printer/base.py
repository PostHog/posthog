import re
from collections.abc import Iterable
from datetime import date, datetime
from difflib import get_close_matches
from typing import Any, Literal, Optional, Union, cast
from uuid import UUID

from django.conf import settings as django_settings

from posthog.schema import MaterializationMode, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.ast import StringType
from posthog.hogql.base import AST
from posthog.hogql.constants import (
    HogQLDialect,
    HogQLGlobalSettings,
    HogQLQuerySettings,
    LimitContext,
    get_max_limit_for_context,
)
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField, FunctionCallTable, Table
from posthog.hogql.errors import ImpossibleASTError, QueryError, ResolutionError
from posthog.hogql.escape_sql import escape_hogql_identifier, escape_hogql_string
from posthog.hogql.functions import find_hogql_aggregation, find_hogql_function, find_hogql_posthog_function
from posthog.hogql.functions.core import validate_function_args
from posthog.hogql.functions.mapping import (
    ALL_EXPOSED_FUNCTION_NAMES,
    HOGQL_COMPARISON_MAPPING,
    is_allowed_parametric_function,
)
from posthog.hogql.printer.types import (
    JoinExprResponse,
    PrintableMaterializedColumn,
    PrintableMaterializedPropertyGroupItem,
)
from posthog.hogql.resolver import resolve_types
from posthog.hogql.resolver_utils import lookup_field_by_name
from posthog.hogql.visitor import Visitor, clone_expr

from posthog.clickhouse.materialized_columns import (
    MaterializedColumn,
    TablesWithMaterializedColumns,
    get_materialized_column_for_property,
)
from posthog.models.property import PropertyName, TableColumn
from posthog.models.team.team import WeekStartDay
from posthog.models.utils import UUIDT

MAX_PLACEHOLDER_MACRO_EXPANSION_DEPTH = 8


def get_channel_definition_dict():
    """Get the channel definition dictionary name with the correct database.
    Evaluated at call time to work with test databases in Python 3.12."""
    return f"{django_settings.CLICKHOUSE_DATABASE}.channel_definition_dict"


def resolve_field_type(expr: ast.Expr) -> ast.Type | None:
    expr_type = expr.type
    while isinstance(expr_type, ast.FieldAliasType):
        expr_type = expr_type.type
    return expr_type


class BasePrinter(Visitor[str]):
    # NOTE: Call "print_ast()", not this class directly.
    # Shared AST walker for all dialect printers (HogQL, ClickHouse, Postgres).
    # Dialect-specific behavior currently lives behind `self.dialect` checks
    # and is being progressively moved into subclass overrides.

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
        self._table_top_level_settings: dict[str, Any] = {}
        self._placeholder_macro_expansion_depth = 0

    def indent(self, extra: int = 0):
        return " " * self.tab_size * (self._indent + extra)

    def _min_function_name(self) -> str:
        """Name of the 2-argument min function for the auto-applied top-level LIMIT cap.

        Defaults to the ClickHouse spelling; dialects with a different name override this.
        """
        return "min2"

    def _render_set_query_limit_percent(self, limit: ast.Expr, limit_str: str) -> str:
        """Render the LIMIT value for a set-operation query when `LIMIT … PERCENT` was used.

        `limit_str` is the already-visited limit expression. The default raises because
        most dialects don't support LIMIT percent; CH and PG override.
        """
        raise QueryError(f"LIMIT percent is not allowed in {self.dialect} dialect")

    def _render_select_query_limit_clause(self, limit: ast.Expr, is_percent: bool) -> str:
        """Render the full LIMIT clause (including the keyword) for a single SELECT.

        Default handles the non-percent case and raises for percent; CH and PG override.
        """
        if is_percent:
            raise QueryError(f"LIMIT percent is not allowed in {self.dialect} dialect")
        return f"LIMIT {self.visit(limit)}"

    def _validate_within_group_for_aggregation(self, node: "ast.Call", func_meta) -> None:
        """Validate that this dialect accepts the WITHIN GROUP clause for `node`.

        Default: permitted. ClickHouse overrides to reject.
        """
        return

    def _render_aggregation_name(self, node: "ast.Call", func_meta) -> str:
        """Render the function name portion of an aggregation call.

        Default: use the ClickHouse name from the function registry. HogQL overrides
        to preserve `node.name` (PR 3).
        """
        return func_meta.clickhouse_name

    def _get_connection_supported_functions(self) -> set[str]:
        metadata = self.context.direct_postgres_connection_metadata
        if not isinstance(metadata, dict):
            return set()

        available_functions = metadata.get("available_functions")
        if not isinstance(available_functions, list):
            return set()

        return {function_name.lower() for function_name in available_functions if isinstance(function_name, str)}

    def visit(self, node: AST | None):
        if node is None:
            return ""
        self.stack.append(node)
        self._indent += 1
        response = super().visit(node)
        self._indent -= 1
        self.stack.pop()

        return response

    def visit_cte(self, node: ast.CTE):
        if node.materialized is not None:
            raise ImpossibleASTError(f"CTE materialization hints are not supported in the '{self.dialect}' dialect")
        if node.using_key is not None:
            raise ImpossibleASTError(f"CTE USING KEY is not supported in the '{self.dialect}' dialect")

        if node.cte_type == "subquery":
            if node.columns is not None:
                raise NotImplementedError("CTE column name lists are not supported in this dialect")
            return f"{self._print_identifier(node.name)} AS {self.visit(node.expr)}"
        return f"{self.visit(node.expr)} AS {self._print_identifier(node.name)}"

    def visit_grouping_set(self, node: ast.GroupingSet):
        inner = ", ".join(self.visit(e) for e in node.exprs)
        return f"({inner})"

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
                if expr.set_operator in ("INTERSECT ALL", "EXCEPT ALL") and self.dialect != "postgres":
                    raise ImpossibleASTError(f"{expr.set_operator} is not supported in the '{self.dialect}' dialect")
                if self.pretty:
                    ret += f"\n{self.indent(1)}{expr.set_operator}\n{self.indent(1)}"
                else:
                    ret += f" {expr.set_operator} "
            ret += query
        self._indent += 1
        if node.limit is not None:
            limit_str = self.visit(node.limit)
            if node.limit_percent:
                limit_str = self._render_set_query_limit_percent(node.limit, limit_str)

            if node.limit_with_ties:
                limit_str += " WITH TIES"
            if self.pretty:
                ret = ret.rstrip() + f"\n{self.indent(1)}LIMIT {limit_str}"
            else:
                ret += f" LIMIT {limit_str}"
        if node.offset is not None:
            offset_str = self.visit(node.offset)
            if self.pretty:
                ret = ret.rstrip() + f"\n{self.indent(1)}OFFSET {offset_str}"
            else:
                ret += f" OFFSET {offset_str}"
        if len(self.stack) > 1:
            return f"({ret.strip()})"
        return ret

    def visit_values_query(self, node: ast.ValuesQuery):
        rows = []
        for row in node.rows:
            values = ", ".join(self.visit(expr) for expr in row)
            rows.append(f"({values})")
        return f"(VALUES {', '.join(rows)})"

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

        ctes = [self.visit(cte) for cte in node.ctes.values()] if node.ctes else None
        has_recursive_cte = any(cte.recursive for cte in node.ctes.values()) if node.ctes else False

        if has_recursive_cte and self.dialect != "postgres":
            raise ImpossibleASTError("Recursive CTEs are only supported in PostgreSQL dialect")

        window = (
            ", ".join(
                [f"{self._print_identifier(name)} AS ({self.visit(expr)})" for name, expr in node.window_exprs.items()]
            )
            if node.window_exprs
            else None
        )
        prewhere = self.visit(node.prewhere) if node.prewhere else None
        where = self.visit(where) if where else None
        group_by: list[str] | None = None
        if node.group_by:
            if node.group_by_mode == "grouping_sets":
                group_by = [self.visit(gs) for gs in node.group_by]
            else:
                group_by = [self.visit(column) for column in node.group_by]
        having = self.visit(node.having) if node.having else None
        if node.qualify is not None and self.dialect != "postgres":
            raise QueryError("QUALIFY is not supported in the '{}' dialect".format(self.dialect))
        qualify = self.visit(node.qualify) if node.qualify else None
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
                raise ImpossibleASTError("Invalid ARRAY JOIN without an array")
            array_join += f" {', '.join(self.visit(expr) for expr in node.array_join_list)}"

        space = f"\n{self.indent(1)}" if self.pretty else " "
        comma = f",\n{self.indent(1)}" if self.pretty else ", "

        clauses = [
            f"WITH{' RECURSIVE' if has_recursive_cte else ''}{space}{comma.join(ctes)}" if ctes else None,
            f"SELECT{space}{'DISTINCT ' if node.distinct else ''}{comma.join(columns)}",
            f"FROM{space}{space.join(joined_tables)}" if len(joined_tables) > 0 else None,
            array_join if array_join else None,
            f"PREWHERE{space}" + prewhere if prewhere else None,
            f"WHERE{space}" + where if where else None,
            (
                f"GROUP BY ALL"
                if node.group_by_mode == "all"
                else f"GROUP BY{space}GROUPING SETS ({comma.join(group_by or [])})"
                if node.group_by_mode == "grouping_sets"
                else f"GROUP BY{space}CUBE({comma.join(group_by or [])})"
                if node.group_by_mode == "cube"
                else f"GROUP BY{space}ROLLUP({comma.join(group_by or [])})"
                if node.group_by_mode == "rollup"
                else f"GROUP BY{space}{comma.join(group_by or [])}"
            )
            if node.group_by_mode == "all" or (group_by and len(group_by) > 0)
            else None,
            f"HAVING{space}" + having if having else None,
            f"QUALIFY{space}" + qualify if qualify else None,
            f"WINDOW{space}" + window if window else None,
            f"ORDER BY{space}{comma.join(order_by)}" if order_by and len(order_by) > 0 else None,
            (
                f"INTERPOLATE ({comma.join(self.visit(expr) for expr in node.interpolate)})"
                if node.interpolate
                else ("INTERPOLATE" if node.interpolate is not None else None)
            ),
        ]

        limit = node.limit
        # TODO: We skip the 50k limit guard when LIMIT % is present. Revisit if we can cap percent limits safely.
        if self.context.limit_top_select and is_top_level_query and not node.limit_percent:
            max_limit = get_max_limit_for_context(self.context.limit_context or LimitContext.QUERY)
            min_function = self._min_function_name()

            if limit is not None:
                if isinstance(limit, ast.Constant) and isinstance(limit.value, int):
                    limit.value = min(limit.value, max_limit)
                else:
                    limit = ast.Call(
                        name=min_function,
                        args=[ast.Constant(value=max_limit), limit],
                    )
            else:
                limit = ast.Constant(value=max_limit)

        if node.limit_by is not None:
            clauses.append(
                f"LIMIT {self.visit(node.limit_by.n)} {f'OFFSET {self.visit(node.limit_by.offset_value)}' if node.limit_by.offset_value else ''} BY {', '.join([self.visit(expr) for expr in node.limit_by.exprs])}"
            )

        if limit is not None:
            if node.limit_with_ties and self.dialect == "postgres":
                raise QueryError("WITH TIES is not supported in postgres dialect")
            limit_str = self._render_select_query_limit_clause(limit, bool(node.limit_percent))
            clauses.append(limit_str)
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
            raise NotImplementedError("BasePrinter._ensure_team_id_where_clause not overridden")

    def _get_table_predicates(
        self,
        table_type: ast.TableType | ast.LazyTableType,
        node_type: ast.TableOrSelectType | None,
    ) -> list[ast.Expr]:
        """Return predicate expressions from the table definition, resolved against the table's type."""
        predicates = table_type.table.get_predicates()
        if not predicates or node_type is None:
            return []

        scope = ast.SelectQueryType(tables={"t": node_type})
        return [resolve_types(clone_expr(pred), self.context, self.dialect, [scope]) for pred in predicates]

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

        if isinstance(node.type, (ast.TableAliasType, ast.ColumnAliasedTableType, ast.TableType)):
            table_type: ast.TableType | ast.LazyTableType | ast.TableAliasType | ast.ColumnAliasedTableType = node.type
            while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
                table_type = cast(
                    ast.TableType | ast.LazyTableType | ast.TableAliasType | ast.ColumnAliasedTableType,
                    table_type.table_type,
                )

            if not isinstance(table_type, ast.TableType) and not isinstance(table_type, ast.LazyTableType):
                raise ImpossibleASTError(f"Invalid table type {type(table_type).__name__} in join_expr")

            self._collect_table_top_level_settings(table_type.table)

            # :IMPORTANT: Ensures team_id filtering on every table. For LEFT JOINs, we add it to the
            # ON clause (not WHERE) to preserve LEFT JOIN semantics - otherwise NULL rows get filtered out.
            team_id_expr = self._ensure_team_id_where_clause(table_type, node.type)
            is_left_join = node.join_type is not None and "LEFT" in node.join_type
            if is_left_join and team_id_expr is not None and node.constraint is not None:
                team_id_for_on_clause = team_id_expr
            else:
                extra_where = team_id_expr

            # Apply table-level predicates (e.g., date filters on PostgresTable).
            predicate_exprs = self._get_table_predicates(table_type, node.type)
            for pred in predicate_exprs:
                if is_left_join and node.constraint is not None:
                    if team_id_for_on_clause is None:
                        team_id_for_on_clause = pred
                    else:
                        team_id_for_on_clause = ast.And(exprs=[team_id_for_on_clause, pred])
                else:
                    if extra_where is None:
                        extra_where = pred
                    else:
                        extra_where = ast.And(exprs=[extra_where, pred])

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

            if (
                isinstance(node.type, (ast.TableAliasType, ast.ColumnAliasedTableType))
                and node.alias is not None
                and node.alias != sql
            ):
                join_strings.append(f"AS {self._print_identifier(node.alias)}")

        elif isinstance(node.type, ast.SelectQueryType):
            join_strings.append(self.visit(node.table))

        elif isinstance(node.type, ast.SelectSetQueryType):
            join_strings.append(self.visit(node.table))

        elif isinstance(node.type, ast.CTETableType):
            join_strings.append(self._print_identifier(node.type.name))

        elif isinstance(node.type, ast.CTETableAliasType):
            join_strings.append(self._print_identifier(node.type.cte_table_type.name))
            join_strings.append(f"AS {self._print_identifier(node.type.alias)}")

        elif isinstance(node.type, ast.SelectViewType) and node.alias is not None:
            join_strings.append(self.visit(node.table))
            join_strings.append(f"AS {self._print_identifier(node.alias)}")

        elif isinstance(node.type, ast.SelectQueryAliasType) and node.alias is not None:
            join_strings.append(self.visit(node.table))
            alias_str = f"AS {self._print_identifier(node.alias)}"
            if node.column_aliases and self.dialect == "postgres":
                col_names = ", ".join(self._print_identifier(c) for c in node.column_aliases)
                alias_str += f" ({col_names})"
            join_strings.append(alias_str)

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

        if node.column_aliases and not isinstance(node.type, ast.SelectQueryAliasType):
            if self.dialect == "postgres":
                col_aliases = ", ".join(self._print_identifier(ca) for ca in node.column_aliases)
                join_strings.append(f"({col_aliases})")

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

    def visit_named_argument(self, node: ast.NamedArgument):
        return f"{self._print_identifier(node.name)} := {self.visit(node.value)}"

    def visit_positional_ref(self, node: ast.PositionalRef):
        if not isinstance(node.index, int) or node.index < 1:
            raise QueryError(f"Positional reference must be a positive integer, got {node.index}")
        return f"#{node.index}"

    def _print_join_expr_chain(self, node: ast.JoinExpr) -> str:
        parts: list[str] = []
        next_join: ast.JoinExpr | None = node
        while isinstance(next_join, ast.JoinExpr):
            visited = self.visit_join_expr(next_join)
            if visited.where is not None:
                raise QueryError("JOIN PIVOT/UNPIVOT cannot apply extra WHERE constraints")
            parts.append(visited.printed_sql)
            next_join = next_join.next_join
        return " ".join(parts)

    def visit_unpivot_expr(self, node: ast.UnpivotExpr):
        if isinstance(node.table, ast.JoinExpr):
            table = self._print_join_expr_chain(node.table)
        else:
            table_expr = self.visit(node.table)
            table = table_expr.printed_sql if isinstance(table_expr, JoinExprResponse) else table_expr
        columns = " ".join(self.visit(col) for col in node.columns)
        include_nulls = "INCLUDE NULLS " if node.include_nulls else ""
        return f"{table} UNPIVOT {include_nulls}({columns})"

    def visit_unpivot_column(self, node: ast.UnpivotColumn):
        value_cols = self.visit(node.value_columns)
        name_cols = self.visit(node.name_columns)
        values = ", ".join(self.visit(val) for val in node.unpivot_values)
        return f"{value_cols} FOR {name_cols} IN ({values})"

    def visit_pivot_expr(self, node: ast.PivotExpr):
        if isinstance(node.table, ast.JoinExpr):
            table = self._print_join_expr_chain(node.table)
        else:
            table_expr = self.visit(node.table)
            table = table_expr.printed_sql if isinstance(table_expr, JoinExprResponse) else table_expr
        aggregates = ", ".join(self.visit(agg) for agg in node.aggregates)
        columns = " ".join(self.visit(col) for col in node.columns)
        group_by = f" GROUP BY {', '.join(self.visit(g) for g in node.group_by)}" if node.group_by else ""
        return f"{table} PIVOT ({aggregates} FOR {columns}{group_by})"

    def visit_pivot_column(self, node: ast.PivotColumn):
        column = self.visit(node.column)
        values = ", ".join(self.visit(val) for val in node.values)
        return f"{column} IN ({values})"

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

    def visit_array_slice(self, node: ast.ArraySlice):
        raise QueryError(f"Array slices are not allowed in {self.dialect} dialect")

    def visit_array(self, node: ast.Array):
        return f"[{', '.join([self.visit(expr) for expr in node.exprs])}]"

    def visit_dict(self, node: ast.Dict):
        tuple_function = "ROW" if self.dialect == "postgres" else "tuple"
        str = f"{tuple_function}('__hx_tag', '__hx_obj'"
        for key, value in node.items:
            str += f", {self.visit(key)}, {self.visit(value)}"
        return str + ")"

    def visit_try_cast(self, node: ast.TryCast):
        raise QueryError(f"TRY_CAST is not allowed in {self.dialect} dialect")

    def visit_lambda(self, node: ast.Lambda):
        identifiers = [self._print_identifier(arg) for arg in node.args]
        if len(identifiers) == 0:
            raise ValueError("Lambdas require at least one argument")
        if len(identifiers) == 1:
            return f"{identifiers[0]} -> {self.visit(node.expr)}"
        return f"({', '.join(identifiers)}) -> {self.visit(node.expr)}"

    def visit_order_expr(self, node: ast.OrderExpr):
        result = f"{self.visit(node.expr)} {node.order}"
        if node.with_fill is not None:
            result += f" {self.visit(node.with_fill)}"
        return result

    def visit_with_fill_expr(self, node: ast.WithFillExpr):
        parts = ["WITH FILL"]
        if node.from_value is not None:
            parts.append(f"FROM {self.visit(node.from_value)}")
        if node.to_value is not None:
            parts.append(f"TO {self.visit(node.to_value)}")
        if node.step_value is not None:
            parts.append(f"STEP {self.visit(node.step_value)}")
        return " ".join(parts)

    def visit_interpolate_expr(self, node: ast.InterpolateExpr):
        if node.value is not None:
            return f"{self.visit(node.expr)} AS {self.visit(node.value)}"
        return self.visit(node.expr)

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
        expr = self._visit_infix_operand(node.expr)
        low = self._visit_infix_operand(node.low)
        high = self._visit_infix_operand(node.high)
        not_kw = " NOT" if node.negated else ""
        op = f"{expr}{not_kw} BETWEEN {low} AND {high}"

        return op

    def visit_is_distinct_from(self, node: ast.IsDistinctFrom):
        left = self._visit_infix_operand(node.left)
        right = self._visit_infix_operand(node.right)
        not_kw = " NOT" if node.negated else ""
        return f"{left} IS{not_kw} DISTINCT FROM {right}"

    def _visit_infix_operand(self, node: ast.Expr) -> str:
        """Visit an operand of an infix keyword operator, parenthesizing Alias
        nodes since AS binds more loosely than BETWEEN / IS DISTINCT FROM."""
        result = self.visit(node)
        if isinstance(node, ast.Alias) and not node.hidden:
            result = f"({result})"
        return result

    def visit_constant(self, node: ast.Constant):
        # Inline everything in HogQL
        return self._print_escaped_string(node.value)

    def visit_keyword(self, node: ast.Keyword):
        if not node.name.isidentifier():
            raise QueryError(f"Invalid keyword name: {node.name}")
        return node.name

    def visit_field(self, node: ast.Field):
        if node.chain == ["*"]:
            return "*"
        # When printing HogQL, we print the properties out as a chain as they are.
        return ".".join([self._print_hogql_identifier_or_index(identifier) for identifier in node.chain])

    def visit_columns_expr(self, node: ast.ColumnsExpr):
        raise ImpossibleASTError("Unexpected ast.ColumnsExpr. This should have been expanded by the resolver.")

    def visit_spread_expr(self, node: ast.SpreadExpr):
        raise ImpossibleASTError(
            "*COLUMNS(...) can only be used to unpack columns inside function call arguments. "
            "Use COLUMNS(...) for top-level column selection."
        )

    def visit_call(self, node: ast.Call):
        func_meta = (
            find_hogql_aggregation(node.name)
            or find_hogql_function(node.name)
            or find_hogql_posthog_function(node.name)
        )

        # Validate parametric arguments
        if func_meta:
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
                    raise QueryError(
                        f"Invalid parametric function in '{node.name}', '{first_arg.value}' is not supported."
                    )

            # Handle format strings in function names before checking function type
            # For HogQL, don't expand the macro, just display it in its original shape.
            if func_meta.using_placeholder_arguments and self.dialect != "hogql":
                return self._render_placeholder_macro(
                    node=node,
                    clickhouse_name=func_meta.clickhouse_name,
                    using_positional_arguments=func_meta.using_positional_arguments,
                )

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
            if func_meta.requires_within_group and node.within_group is None:
                raise QueryError(f"Aggregation '{node.name}' requires WITHIN GROUP")
            self._validate_within_group_for_aggregation(node, func_meta)

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

            arg_strings = [self.visit(arg) for arg in node.args]
            params = [self.visit(param) for param in node.params] if node.params is not None else None
            within_group = (
                f" WITHIN GROUP (ORDER BY {', '.join(self.visit(expr) for expr in node.within_group)})"
                if node.within_group
                else ""
            )

            params_part = f"({', '.join(params)})" if params is not None else ""
            order_by_part = f" ORDER BY {', '.join(self.visit(o) for o in node.order_by)}" if node.order_by else ""
            args_body = f"{'DISTINCT ' if node.distinct else ''}{', '.join(arg_strings)}{order_by_part}"
            args_part = (
                ""
                if node.within_group is not None and len(arg_strings) == 0 and not node.distinct and not node.order_by
                else f"({args_body})"
            )

            if node.within_group is not None and not func_meta.requires_within_group:
                raise QueryError(f"Aggregation '{node.name}' does not support WITHIN GROUP")

            filter_part = f" FILTER (WHERE {self.visit(node.filter_expr)})" if node.filter_expr else ""
            return (
                f"{self._render_aggregation_name(node, func_meta)}{params_part}{args_part}{within_group}{filter_part}"
            )

        elif func_meta := find_hogql_function(node.name):
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

            return self._render_function_call(node, func_meta)
        elif func_meta := find_hogql_posthog_function(node.name):
            validate_function_args(
                node.args,
                func_meta.min_args,
                func_meta.max_args,
                node.name,
            )

            return self._render_posthog_function_call(node, func_meta)
        else:
            if self.dialect == "hogql" and node.name.lower() in self._get_connection_supported_functions():
                return f"{node.name}({', '.join([self.visit(arg) for arg in node.args])})"

            close_matches = get_close_matches(node.name, ALL_EXPOSED_FUNCTION_NAMES, 1)
            if len(close_matches) > 0:
                raise QueryError(
                    f"Unsupported function call '{node.name}(...)'. Perhaps you meant '{close_matches[0]}(...)'?"
                )
            raise QueryError(f"Unsupported function call '{node.name}(...)'")

    def _render_function_call(self, node: "ast.Call", func_meta) -> str:
        """Render a standard HogQL function call. Default is the HogQL/pass-through shape; CH overrides."""
        order_by_part = f" ORDER BY {', '.join(self.visit(o) for o in node.order_by)}" if node.order_by else ""
        filter_part = f" FILTER (WHERE {self.visit(node.filter_expr)})" if node.filter_expr else ""
        return f"{node.name}({', '.join([self.visit(arg) for arg in node.args])}{order_by_part}){filter_part}"

    def _render_posthog_function_call(self, node: "ast.Call", func_meta) -> str:
        """Render a PostHog-extension function call. Default is HogQL pass-through; CH overrides."""
        args = [self.visit(arg) for arg in node.args]
        return f"{node.name}({', '.join(args)})"

    def _yield_property_group_columns(self, field_type, table_name: str, field_name: str, property_name: str):
        """Yield printable property-group column accessors for this dialect.

        Default yields nothing (property groups are a ClickHouse-only storage optimization).
        """
        yield from ()

    def visit_placeholder(self, node: ast.Placeholder):
        if node.field is None:
            raise QueryError("You can not use placeholders here")
        raise QueryError(f"Unresolved placeholder: {{{node.field}}}")

    def _render_placeholder_macro(self, node: ast.Call, clickhouse_name: str, using_positional_arguments: bool) -> str:
        self._placeholder_macro_expansion_depth += 1
        try:
            if self._placeholder_macro_expansion_depth > MAX_PLACEHOLDER_MACRO_EXPANSION_DEPTH:
                raise QueryError(
                    f"Function '{node.name}' exceeded maximum placeholder macro depth of {MAX_PLACEHOLDER_MACRO_EXPANSION_DEPTH}."
                )

            if using_positional_arguments:
                arg_arr = [self.visit(arg) for arg in node.args]
                try:
                    rendered = clickhouse_name.format(*arg_arr)
                except (KeyError, IndexError) as e:
                    raise QueryError(f"Invalid argument reference in function '{node.name}': {str(e)}")
            else:
                placeholder_count = clickhouse_name.count("{}")
                if len(node.args) != placeholder_count:
                    raise QueryError(
                        f"Function '{node.name}' requires exactly {placeholder_count} argument{'s' if placeholder_count != 1 else ''}"
                    )
                rendered = clickhouse_name.format(*[self.visit(arg) for arg in node.args])

            return rendered
        finally:
            self._placeholder_macro_expansion_depth -= 1

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

    def visit_column_aliased_table_type(self, type: ast.ColumnAliasedTableType):
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
            or isinstance(type.table_type, ast.ColumnAliasedTableType)
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
                # For column-aliased tables in postgres, use the aliased name
                # (the DB handles renaming via the (a,b,c) syntax). For other
                # dialects, use the real DB column name.
                if isinstance(type.table_type, ast.ColumnAliasedTableType) and self.dialect == "postgres":
                    field_sql = self._print_identifier(type.name)
                else:
                    # resolved_field may be an ast.Alias; in both cases .name is the physical column name to emit
                    if not isinstance(resolved_field, DatabaseField):
                        raise QueryError(f"Can't resolve field {type.name}")
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
            or isinstance(type.table_type, ast.CTETableType)
            or isinstance(type.table_type, ast.CTETableAliasType)
        ):
            field_sql = self._print_identifier(type.name)
            if (
                isinstance(type.table_type, ast.SelectQueryAliasType)
                or isinstance(type.table_type, ast.SelectViewType)
                or isinstance(type.table_type, ast.CTETableType)
                or isinstance(type.table_type, ast.CTETableAliasType)
            ):
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
                error += " Lazy joins should have all been replaced in the resolver."
            raise ImpossibleASTError(error)

        return field_sql

    def _get_materialized_property_source_for_property_type(
        self, type: ast.PropertyType
    ) -> PrintableMaterializedColumn | PrintableMaterializedPropertyGroupItem | None:
        """
        Find the most efficient materialized property source for the provided property type.
        """
        for source in self._get_all_materialized_property_sources(type.field_type, str(type.chain[0])):
            return source
        return None

    def _get_table_name(self, table: ast.TableType) -> str:
        return table.table.to_printed_hogql()

    def _get_all_materialized_property_sources(
        self, field_type: ast.FieldType, property_name: str
    ) -> Iterable[PrintableMaterializedColumn | PrintableMaterializedPropertyGroupItem]:
        """
        Find all materialized property sources for the provided field type and property name, ordered from what is
        likely to be the most efficient access path to the least efficient.
        """
        # TODO: It likely makes sense to make this independent of whether or not property groups are used.
        if self.context.modifiers.materializationMode == "disabled":
            return

        field = field_type.resolve_database_field(self.context)

        # check for a materialised column
        table = field_type.table_type
        while isinstance(table, (ast.TableAliasType, ast.ColumnAliasedTableType, ast.VirtualTableType)):
            table = table.table_type

        if isinstance(table, ast.TableType):
            table_name = self._get_table_name(table)

            if field is None:
                raise QueryError(f"Can't resolve field {field_type.name} on table {table_name}")
            if not isinstance(field, DatabaseField):
                raise QueryError(f"Can't resolve field {field_type.name} on table {table_name}")
            field_name = cast(Union[Literal["properties"], Literal["person_properties"]], field.name)

            materialized_column = self._get_materialized_column(table_name, property_name, field_name)
            if materialized_column is not None:
                yield PrintableMaterializedColumn(
                    self.visit(field_type.table_type),
                    self._print_identifier(materialized_column.name),
                    is_nullable=materialized_column.is_nullable,
                    has_minmax_index=materialized_column.has_minmax_index,
                    has_ngram_lower_index=materialized_column.has_ngram_lower_index,
                    has_bloom_filter_index=materialized_column.has_bloom_filter_index,
                )

            # Check for dmat (dynamic materialized) columns
            if dmat_column := self._get_dmat_column(table_name, field_name, property_name):
                yield PrintableMaterializedColumn(
                    self.visit(field_type.table_type),
                    self._print_identifier(dmat_column),
                    is_nullable=True,
                    has_minmax_index=False,
                    has_ngram_lower_index=False,
                    has_bloom_filter_index=False,
                )

            yield from self._yield_property_group_columns(field_type, table_name, field_name, property_name)
        elif self.context.within_non_hogql_query and (
            isinstance(table, ast.SelectQueryAliasType) and table.alias == "events__pdi__person"
        ):
            # :KLUDGE: Legacy person properties handling. Only used within non-HogQL queries, such as insights.
            if self.context.modifiers.personsOnEventsMode != PersonsOnEventsMode.DISABLED:
                materialized_column = self._get_materialized_column("events", property_name, "person_properties")
            else:
                materialized_column = self._get_materialized_column("person", property_name, "properties")
            if materialized_column is not None:
                yield PrintableMaterializedColumn(
                    None,
                    self._print_identifier(materialized_column.name),
                    is_nullable=materialized_column.is_nullable,
                    has_minmax_index=materialized_column.has_minmax_index,
                    has_ngram_lower_index=materialized_column.has_ngram_lower_index,
                    has_bloom_filter_index=materialized_column.has_bloom_filter_index,
                )

    def visit_property_type(self, type: ast.PropertyType):
        if type.joined_subquery is not None and type.joined_subquery_field_name is not None:
            return f"{self._print_identifier(type.joined_subquery.alias)}.{self._print_identifier(type.joined_subquery_field_name)}"

        materialized_property_source = self._get_materialized_property_source_for_property_type(type)
        if materialized_property_source is not None:
            # Special handling for $ai_trace_id, $ai_session_id, and $ai_is_error to avoid nullIf wrapping for index optimization
            if (
                len(type.chain) == 1
                and type.chain[0] in ("$ai_trace_id", "$ai_session_id", "$ai_is_error")
                and isinstance(materialized_property_source, PrintableMaterializedColumn)
            ):
                materialized_property_sql = str(materialized_property_source)
            elif (
                isinstance(materialized_property_source, PrintableMaterializedColumn)
                and not materialized_property_source.is_nullable
            ):
                # TODO: rematerialize all columns to properly support empty strings and "null" string values.
                if self.context.modifiers.materializationMode == MaterializationMode.LEGACY_NULL_AS_STRING:
                    materialized_property_sql = f"nullIf({materialized_property_source}, '')"
                else:  # MaterializationMode AUTO or LEGACY_NULL_AS_NULL
                    materialized_property_sql = f"nullIf(nullIf({materialized_property_source}, ''), 'null')"
            else:
                materialized_property_sql = str(materialized_property_source)

            if len(type.chain) == 1:
                return materialized_property_sql
            else:
                return self._unsafe_json_extract_trim_quotes(
                    materialized_property_sql,
                    self._json_property_args(type.chain[1:]),
                )

        return self._unsafe_json_extract_trim_quotes(self.visit(type.field_type), self._json_property_args(type.chain))

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

    def visit_ctetable_type(self, type: ast.CTETableType):
        return self._print_identifier(type.name)

    def visit_ctetable_alias_type(self, type: ast.CTETableAliasType):
        return self._print_identifier(type.alias)

    def visit_field_alias_type(self, type: ast.FieldAliasType):
        return self._print_identifier(type.alias)

    def visit_expression_field_type(self, type: ast.ExpressionFieldType):
        return self.visit(type.expr)

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

    def visit_window_function(self, node: ast.WindowFunction):
        identifier = self._print_identifier(node.name)
        exprs = [self.visit(expr) for expr in node.exprs or []]
        cloned_node = cast(ast.WindowFunction, clone_expr(node))

        # For compatibility with ClickHouse syntax, convert lag/lead to lagInFrame/leadInFrame and add default window frame if needed
        if identifier in ("lag", "lead") and self.dialect != "postgres":
            identifier = f"{identifier}InFrame"
            # Wrap the first expression (value) and third expression (default) in toNullable()
            # The second expression (offset) must remain a non-nullable integer
            if len(exprs) > 0:
                exprs[0] = f"toNullable({exprs[0]})"  # value
            # If there's no window frame specified, add the default one
            if not cloned_node.over_expr and not cloned_node.over_identifier:
                cloned_node.over_expr = self._create_default_window_frame(cloned_node)
            # If there's an over_identifier, we need to extract the new window expr just for this function
            elif cloned_node.over_identifier:
                # Find the last select query to look up the window definition
                last_select = self._last_select()
                if last_select and last_select.window_exprs and cloned_node.over_identifier in last_select.window_exprs:
                    base_window = last_select.window_exprs[cloned_node.over_identifier]
                    # Create a new window expr based on the referenced one
                    cloned_node.over_expr = ast.WindowExpr(
                        partition_by=base_window.partition_by,
                        order_by=base_window.order_by,
                        frame_method="ROWS" if not base_window.frame_method else base_window.frame_method,
                        frame_start=base_window.frame_start
                        or ast.WindowFrameExpr(frame_type="PRECEDING", frame_value=None),
                        frame_end=base_window.frame_end
                        or ast.WindowFrameExpr(frame_type="FOLLOWING", frame_value=None),
                    )
                    cloned_node.over_identifier = None
            # If there's an ORDER BY but no frame, add the default frame
            elif cloned_node.over_expr and cloned_node.over_expr.order_by and not cloned_node.over_expr.frame_method:
                cloned_node.over_expr = self._create_default_window_frame(cloned_node)

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
        if node.frame_type in ("PRECEDING", "FOLLOWING"):
            if node.frame_value is None:
                value_str = "UNBOUNDED"
            elif isinstance(node.frame_value, int):
                value_str = str(node.frame_value)
            else:
                value_str = self.visit(node.frame_value)
            return f"{value_str} {node.frame_type}"
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

    def _get_materialized_column(
        self, table_name: str, property_name: PropertyName, field_name: TableColumn
    ) -> MaterializedColumn | None:
        return get_materialized_column_for_property(
            cast(TablesWithMaterializedColumns, table_name), field_name, property_name
        )

    def _get_dmat_column(self, table_name: str, field_name: str, property_name: str) -> str | None:
        """
        Get the dmat column name for a property if available.

        Returns the column name (e.g., 'dmat_numeric_3') if a materialized slot exists,
        otherwise None.
        """
        if self.context.property_swapper is None:
            return None

        # Only event properties have dmat columns
        if table_name != "events" or field_name != "properties":
            return None

        prop_info = self.context.property_swapper.event_properties.get(property_name)
        if prop_info:
            return prop_info.get("dmat")

        return None

    def _get_timezone(self) -> str:
        if self.context.modifiers.convertToProjectTimezone is False:
            return "UTC"
        return self.context.database.get_timezone() if self.context.database else "UTC"

    def _get_week_start_day(self) -> WeekStartDay:
        return self.context.database.get_week_start_day() if self.context.database else WeekStartDay.SUNDAY

    def _is_type_nullable(self, node_type: ast.Type) -> bool | None:
        if isinstance(node_type, ast.PropertyType):
            return True
        elif isinstance(node_type, ast.ConstantType):
            return node_type.nullable
        elif isinstance(node_type, ast.CallType):
            return node_type.return_type.nullable
        elif isinstance(node_type, ast.FieldType):
            return node_type.is_nullable(self.context)
        return None

    def _is_nullable(self, node: ast.Expr) -> bool:
        if isinstance(node, ast.Constant):
            return node.value is None
        elif node.type and (nullable := self._is_type_nullable(node.type)) is not None:
            return nullable
        elif isinstance(node, ast.Alias):
            return self._is_nullable(node.expr)
        elif (
            isinstance(node.type, ast.FieldAliasType)
            and (field_type := resolve_field_type(node))
            and (nullable := self._is_type_nullable(field_type)) is not None
        ):
            return nullable
        return True

    def _collect_table_top_level_settings(self, table: Table) -> None:
        if table.top_level_settings is None:
            return
        for key, value in table.top_level_settings.model_dump().items():
            if value is None:
                continue
            existing = self._table_top_level_settings.get(key)
            if existing is not None and existing != value:
                raise QueryError(
                    f"Conflicting top_level_settings for '{key}': "
                    f"one table requires {existing!r} but another requires {value!r}"
                )
            self._table_top_level_settings[key] = value

    def _merge_table_top_level_settings(self, settings: HogQLQuerySettings | None) -> dict[str, Any]:
        merged = dict(settings.model_dump()) if settings else {}
        if not self._table_top_level_settings:
            return merged
        for key, value in self._table_top_level_settings.items():
            existing = merged.get(key)
            if existing is not None and existing != value:
                raise QueryError(
                    f"Conflicting settings for '{key}': query has {existing!r} but table requires {value!r}"
                )
            merged[key] = value
        return merged

    def _print_settings(self, settings: HogQLQuerySettings | dict[str, Any]) -> str | None:
        pairs = []
        items = settings.items() if isinstance(settings, dict) else settings
        for key, value in items:
            if value is None:
                continue
            if not re.match(r"^[a-zA-Z0-9_]+$", key):
                raise QueryError(f"Setting {key} is not supported")
            if isinstance(value, bool):
                pairs.append(f"{key}={1 if value else 0}")
            elif isinstance(value, int) or isinstance(value, float):
                pairs.append(f"{key}={value}")
            elif isinstance(value, list):
                if not all(isinstance(item, str) and item for item in value):
                    raise QueryError(f"List setting {key} can only contain non-empty strings")
                formatted_items = ", ".join(self._print_hogql_identifier_or_index(item) for item in value)
                pairs.append(f"{key}={self._print_escaped_string(formatted_items)}")
            elif isinstance(value, str):
                pairs.append(f"{key}={self._print_escaped_string(value)}")
            else:
                raise QueryError(f"Setting {key} has unsupported type {type(value).__name__}")
        if len(pairs) > 0:
            return f"SETTINGS {', '.join(pairs)}"
        return None

    def _create_default_window_frame(self, node: ast.WindowFunction):
        # For lag/lead functions, we need to order by the first argument by default
        order_by: list[ast.OrderExpr] | None = None
        if node.over_expr and node.over_expr.order_by:
            order_by = [cast(ast.OrderExpr, clone_expr(expr)) for expr in node.over_expr.order_by]
        elif node.exprs is not None and len(node.exprs) > 0:
            order_by = [ast.OrderExpr(expr=clone_expr(node.exprs[0]), order="ASC")]

        # Preserve existing PARTITION BY if provided via an existing OVER () clause
        partition_by: list[ast.Expr] | None = None
        if node.over_expr and node.over_expr.partition_by:
            partition_by = [cast(ast.Expr, clone_expr(expr)) for expr in node.over_expr.partition_by]

        return ast.WindowExpr(
            partition_by=partition_by,
            order_by=order_by,
            frame_method="ROWS",
            frame_start=ast.WindowFrameExpr(frame_type="PRECEDING", frame_value=None),
            frame_end=ast.WindowFrameExpr(frame_type="FOLLOWING", frame_value=None),
        )

    def visit_type_cast(self, node: ast.TypeCast):
        match node.type_name.lower():
            case "int" | "integer":
                return f"toInt64({self.visit(node.expr)})"
            case "float" | "double" | "double precision" | "real":
                return f"toFloat64({self.visit(node.expr)})"
            case "text" | "varchar" | "char" | "string":
                return f"toString({self.visit(node.expr)})"
            case "boolean" | "bool":
                return f"toBoolean({self.visit(node.expr)})"
            case "date":
                return f"toDate({self.visit(node.expr)})"
            case (
                "datetime" | "timestamp" | "timestamptz" | "timestamp with time zone" | "timestamp with local time zone"
            ):
                return f"toDateTime({self.visit(node.expr)}, '{self._get_timezone()}')"
            case _:
                raise QueryError(f"Unsupported type cast to '{node.type_name}'")
