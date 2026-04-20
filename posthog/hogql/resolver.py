import dataclasses
from datetime import date, datetime
from typing import Any, Optional, cast
from uuid import UUID

import re2

from posthog.hogql import ast
from posthog.hogql.ast import ConstantType, FieldTraverserType
from posthog.hogql.base import _T_AST
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import FunctionCallTable, LazyTable, SavedQuery, StringJSONDatabaseField
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.persons import PersonsTable
from posthog.hogql.errors import ImpossibleASTError, NotImplementedError, QueryError, ResolutionError
from posthog.hogql.escape_sql import safe_identifier
from posthog.hogql.functions import find_hogql_posthog_function
from posthog.hogql.functions.action import matches_action
from posthog.hogql.functions.cohort import cohort_query_node
from posthog.hogql.functions.core import compare_types, validate_function_args
from posthog.hogql.functions.explain_csp_report import explain_csp_report
from posthog.hogql.functions.mapping import HOGQL_CLICKHOUSE_FUNCTIONS
from posthog.hogql.functions.recording_button import recording_button
from posthog.hogql.functions.sparkline import sparkline
from posthog.hogql.functions.survey import get_survey_response, unique_survey_submissions_filter
from posthog.hogql.functions.traffic_type import (
    get_bot_name,
    get_bot_type,
    get_traffic_category,
    get_traffic_type,
    is_bot,
)
from posthog.hogql.hogqlx import HOGQLX_COMPONENTS, HOGQLX_TAGS, convert_to_hx
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver_utils import expand_hogqlx_query, lookup_field_by_name, lookup_table_by_name
from posthog.hogql.utils import map_virtual_properties
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.models.utils import UUIDT

# https://github.com/ClickHouse/ClickHouse/issues/23194 - "Describe how identifiers in SELECT queries are resolved"

# To quickly disable global joins, switch this to False
USE_GLOBAL_JOINS = False

EMPTY_SCOPE = ast.SelectQueryType()

type PostgresKeywordType = type[ast.DateType] | type[ast.DateTimeType]

POSTGRES_KEYWORD_TYPES: dict[str, PostgresKeywordType] = {
    "current_date": ast.DateType,
    "current_time": ast.DateTimeType,
    "current_timestamp": ast.DateTimeType,
    "localtime": ast.DateTimeType,
    "localtimestamp": ast.DateTimeType,
}


def resolve_constant_data_type(constant: Any) -> ConstantType:
    if constant is None:
        return ast.UnknownType()
    if isinstance(constant, bool):
        return ast.BooleanType(nullable=False)
    if isinstance(constant, int):
        return ast.IntegerType(nullable=False)
    if isinstance(constant, float):
        return ast.FloatType(nullable=False)
    if isinstance(constant, str):
        return ast.StringType(nullable=False)
    if isinstance(constant, list):
        unique_types = {str(resolve_constant_data_type(item)) for item in constant}
        return ast.ArrayType(
            nullable=False,
            item_type=resolve_constant_data_type(constant[0]) if len(unique_types) == 1 else ast.UnknownType(),
        )
    if isinstance(constant, tuple):
        return ast.TupleType(nullable=False, item_types=[resolve_constant_data_type(item) for item in constant])
    if isinstance(constant, datetime) or type(constant).__name__ == "FakeDatetime":
        return ast.DateTimeType(nullable=False)
    if isinstance(constant, date) or type(constant).__name__ == "FakeDate":
        return ast.DateType(nullable=False)
    if isinstance(constant, UUID) or isinstance(constant, UUIDT):
        return ast.UUIDType(nullable=False)
    raise ImpossibleASTError(f"Unsupported constant type: {type(constant)}")


def resolve_types_from_table(
    expr: ast.Expr, table_chain: list[str], context: HogQLContext, dialect: HogQLDialect
) -> ast.Expr:
    if context.database is None:
        raise QueryError("Database needs to be defined")

    if not context.database.has_table(table_chain):
        raise QueryError(f'Table "{".".join(table_chain)}" does not exist')

    select_node = ast.SelectQuery(
        select=[ast.Field(chain=["*"])],
        select_from=ast.JoinExpr(table=ast.Field(chain=cast(list[str | int], table_chain))),
    )
    select_node_with_types = cast(ast.SelectQuery, resolve_types(select_node, context, dialect))
    assert select_node_with_types.type is not None

    return resolve_types(expr, context, dialect, [select_node_with_types.type])


def resolve_types(
    node: _T_AST,
    context: HogQLContext,
    dialect: HogQLDialect,
    scopes: Optional[list[ast.SelectQueryType]] = None,
) -> _T_AST:
    return Resolver(scopes=scopes, context=context, dialect=dialect).visit(node)


class AliasCollector(TraversingVisitor):
    def __init__(self):
        super().__init__()
        self.aliases: list[str] = []

    def visit_alias(self, node: ast.Alias):
        self.aliases.append(node.alias)
        return node


class FieldCollector(TraversingVisitor):
    def __init__(self):
        super().__init__()
        self.fields: list[ast.Field] = []

    def visit_field(self, node: ast.Field):
        self.fields.append(node)
        return node


class Resolver(CloningVisitor):
    """The Resolver visits an AST and 1) resolves all fields, 2) assigns types to nodes, 3) expands all CTEs."""

    def __init__(
        self,
        context: HogQLContext,
        dialect: HogQLDialect = "clickhouse",
        scopes: Optional[list[ast.SelectQueryType]] = None,
    ):
        super().__init__()
        # Each SELECT query creates a new scope (type). Store all of them in a list as we traverse the tree.
        self.scopes: list[ast.SelectQueryType] = scopes or []
        self.ctes: dict[str, ast.CTE] = {}
        self.current_view_depth: int = 0
        self.context = context
        self.dialect = dialect
        self.database = context.database
        self.cte_counter = 0
        self._scope_table_names: dict[int, dict[str, str]] = {}
        self._scope_table_column_aliases: dict[int, dict[str, list[str]]] = {}

    def _get_scope_table_names(self, scope: ast.SelectQueryType) -> dict[str, str]:
        return self._scope_table_names.setdefault(id(scope), {})

    def _get_scope_table_column_aliases(self, scope: ast.SelectQueryType) -> dict[str, list[str]]:
        return self._scope_table_column_aliases.setdefault(id(scope), {})

    def visit(self, node: ast.AST | None):
        if isinstance(node, ast.Expr) and node.type is not None:
            raise ResolutionError(
                f"Type already resolved for {type(node).__name__} ({type(node.type).__name__}). Can't run again."
            )
        return super().visit(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery):
        parent_ctes = self.ctes
        self.ctes = dict(parent_ctes)

        if node.limit_with_ties and self.dialect == "postgres":
            raise QueryError("WITH TIES is not supported in postgres dialect")

        initial = self.visit(node.initial_select_query)

        # Root WITH propagates to all subsequent branches. Branch-level CTEs shadow root CTEs.
        if isinstance(initial, ast.SelectQuery) and initial.ctes:
            for name, cte in initial.ctes.items():
                self.ctes[name] = cte

        subsequent: list[ast.SelectSetNode] = []
        for expr in node.subsequent_select_queries:
            subsequent.append(
                ast.SelectSetNode(set_operator=expr.set_operator, select_query=self.visit(expr.select_query))
            )

        result = ast.SelectSetQuery(
            start=node.start,
            end=node.end,
            initial_select_query=initial,
            subsequent_select_queries=subsequent,
            limit=self.visit(node.limit) if node.limit is not None else None,
            offset=self.visit(node.offset) if node.offset is not None else None,
            limit_percent=node.limit_percent,
            limit_with_ties=node.limit_with_ties,
        )
        result.type = ast.SelectSetQueryType(
            types=[result.initial_select_query.type, *(x.select_query.type for x in result.subsequent_select_queries)]  # type: ignore
        )

        self.ctes = parent_ctes

        return result

    def visit_values_query(self, node: ast.ValuesQuery):
        resolved_rows: list[list[ast.Expr]] = []
        for row in node.rows:
            resolved_rows.append([self.visit(expr) for expr in row])

        if resolved_rows:
            expected_len = len(resolved_rows[0])
            for i, row in enumerate(resolved_rows):
                if len(row) != expected_len:
                    raise QueryError(f"VALUES row {i + 1} has {len(row)} columns, expected {expected_len}")

        columns: dict[str, ast.Type] = {}
        if resolved_rows:
            for j, expr in enumerate(resolved_rows[0]):
                col_name = f"col{j}"
                columns[col_name] = expr.type or ast.UnknownType()

        result = ast.ValuesQuery(
            start=node.start,
            end=node.end,
            rows=resolved_rows,
        )
        result.type = ast.SelectQueryType(columns=columns)
        return result

    def visit_unpivot_expr(self, node: ast.UnpivotExpr):
        if self.dialect != "postgres":
            raise QueryError(f"UNPIVOT is not allowed in {self.dialect} dialect")

        node = cast(ast.UnpivotExpr, clone_expr(node))

        # Resolve the source table in an isolated scope so we can use its columns.
        temp_scope = ast.SelectQueryType()
        self.scopes.append(temp_scope)
        try:
            if isinstance(node.table, ast.JoinExpr):
                temp_join = self.visit_join_expr(node.table)
                node.table = temp_join
            else:
                temp_join = self.visit_join_expr(ast.JoinExpr(table=cast(ast.Field, node.table)))
                node.table = cast(ast.Expr, temp_join.table)
            base_type = temp_join.type

            resolved_columns: list[ast.UnpivotColumn] = []
            unpivoted_names: set[str] = set()

            def _extract_unpivot_field(expr: ast.Expr) -> ast.Field | None:
                if isinstance(expr, ast.Field):
                    return expr
                if isinstance(expr, ast.Alias) and isinstance(expr.expr, ast.Field):
                    return expr.expr
                return None

            def resolve_unpivot_value(expr: ast.Expr) -> ast.Expr:
                resolved = self.visit(expr)
                field = _extract_unpivot_field(resolved)
                if field and field.chain:
                    unpivoted_names.add(str(field.chain[-1]))
                return field if field is not None else resolved

            for col in node.columns:
                resolved_values = [resolve_unpivot_value(val) for val in col.unpivot_values]
                resolved_columns.append(
                    ast.UnpivotColumn(
                        value_columns=clone_expr(col.value_columns),
                        name_columns=clone_expr(col.name_columns),
                        unpivot_values=resolved_values,
                    )
                )

            node.columns = resolved_columns

            for col in node.columns:
                value_is_tuple = isinstance(col.value_columns, ast.Tuple)
                name_is_tuple = isinstance(col.name_columns, ast.Tuple)
                value_len = len(cast(ast.Tuple, col.value_columns).exprs) if value_is_tuple else 1
                name_len = len(cast(ast.Tuple, col.name_columns).exprs) if name_is_tuple else 1

                if value_is_tuple != name_is_tuple:
                    raise QueryError("UNPIVOT value and name columns must both be tuples or both be single columns")
                if value_len != name_len:
                    raise QueryError(f"UNPIVOT value/name column tuple lengths must match ({value_len} vs {name_len})")

                for value in col.unpivot_values:
                    value_is_value_tuple = isinstance(value, ast.Tuple)
                    if value_is_tuple:
                        if not value_is_value_tuple:
                            raise QueryError(f"UNPIVOT IN values must be tuples of length {value_len}")
                        if len(cast(ast.Tuple, value).exprs) != value_len:
                            raise QueryError(f"UNPIVOT IN values must be tuples of length {value_len}")
                    else:
                        if value_is_value_tuple:
                            raise QueryError("UNPIVOT IN values must be single columns")

            columns: dict[str, ast.Type] = {}

            def add_column(name: str, column_type: ast.Type | None) -> None:
                if name in columns:
                    return
                columns[name] = column_type or ast.UnknownType()

            base_field_names: set[str] = set()
            if isinstance(base_type, ast.SelectQueryAliasType):
                base_type = base_type.select_query_type

            if isinstance(base_type, ast.SelectSetQueryType):
                base_type = base_type.types[0]

            if isinstance(base_type, ast.SelectQueryType):
                base_field_names = set(base_type.columns.keys())
                for name, col_type in base_type.columns.items():
                    if name not in unpivoted_names:
                        add_column(name, col_type)
            elif isinstance(base_type, ast.BaseTableType):
                base_field_names = set(base_type.resolve_database_table(self.context).get_asterisk().keys())
                for name in base_field_names:
                    if name not in unpivoted_names:
                        add_column(name, None)

            # Ensure unpivoted columns are not exposed from the base table.
            fallback_unpivoted: set[str] = set()
            for col in node.columns:
                for value in col.unpivot_values:
                    if isinstance(value, ast.Field) and value.chain:
                        fallback_unpivoted.add(str(value.chain[-1]))
            for name in unpivoted_names.union(fallback_unpivoted):
                columns.pop(name, None)

            def normalize_output_columns(expr: ast.Expr) -> tuple[ast.Expr, list[str]]:
                if isinstance(expr, ast.Tuple):
                    exprs = expr.exprs
                else:
                    exprs = [expr]
                names: list[str] = []
                normalized: list[ast.Expr] = []
                for item in exprs:
                    if isinstance(item, ast.Field) and len(item.chain) == 1:
                        name = str(item.chain[0])
                        names.append(name)
                        field = cast(ast.Field, clone_expr(item))
                        field.type = field.type or ast.UnknownType()
                        normalized.append(field)
                    else:
                        raise QueryError("UNPIVOT columns must be identifiers")
                if isinstance(expr, ast.Tuple):
                    return ast.Tuple(exprs=normalized), names
                return normalized[0], names

            def ensure_unpivot_value_valid(expr: ast.Expr) -> None:
                field = _extract_unpivot_field(expr)
                if not field or not field.chain:
                    return
                name = str(field.chain[-1])
                if base_field_names and name not in base_field_names:
                    raise QueryError(f'UNPIVOT value column "{name}" was not found in the source table')

            normalized_columns: list[ast.UnpivotColumn] = []
            for col in node.columns:
                value_expr, value_names = normalize_output_columns(col.value_columns)
                name_expr, name_names = normalize_output_columns(col.name_columns)
                for name in value_names:
                    add_column(name, None)
                for name in name_names:
                    add_column(name, None)
                for value in col.unpivot_values:
                    ensure_unpivot_value_valid(value)
                normalized_columns.append(
                    ast.UnpivotColumn(
                        value_columns=value_expr,
                        name_columns=name_expr,
                        unpivot_values=col.unpivot_values,
                    )
                )

            node.columns = normalized_columns

            select_query_type = ast.SelectQueryType(columns=columns)
            node.type = select_query_type

            # Final safety: ensure unpivoted value columns are removed from output columns.
            to_remove: set[str] = set()
            for col in node.columns:
                for value in col.unpivot_values:
                    field = _extract_unpivot_field(value)
                    if field and field.chain:
                        to_remove.add(str(field.chain[-1]))
            for name in to_remove:
                select_query_type.columns.pop(name, None)

            # Remove unpivoted columns by name from the original source list as well.
            for col in node.columns:
                for value in col.unpivot_values:
                    field = _extract_unpivot_field(value)
                    if field and field.chain:
                        select_query_type.columns.pop(str(field.chain[-1]), None)

            def attach_unpivot_types(expr: ast.Expr) -> None:
                if isinstance(expr, ast.Tuple):
                    for item in expr.exprs:
                        attach_unpivot_types(item)
                    return
                if isinstance(expr, ast.Field) and len(expr.chain) == 1:
                    name = str(expr.chain[0])
                    expr.type = ast.FieldType(name=name, table_type=select_query_type)

            for col in node.columns:
                attach_unpivot_types(col.value_columns)
                attach_unpivot_types(col.name_columns)
            return node
        finally:
            self.scopes.pop()

    def visit_pivot_expr(self, node: ast.PivotExpr):
        if self.dialect != "postgres":
            raise QueryError(f"PIVOT is not allowed in {self.dialect} dialect")

        node = cast(ast.PivotExpr, clone_expr(node))

        # Resolve the source table in an isolated scope so we can use its columns.
        temp_scope = ast.SelectQueryType()
        self.scopes.append(temp_scope)
        try:
            if isinstance(node.table, ast.JoinExpr):
                temp_join = self.visit_join_expr(node.table)
                node.table = temp_join
            else:
                temp_join = self.visit_join_expr(ast.JoinExpr(table=cast(ast.Field, node.table)))
                node.table = cast(ast.Expr, temp_join.table)
            base_type = temp_join.type

            node.aggregates = [self.visit(expr) for expr in node.aggregates]
            node.columns = [self.visit(col) for col in node.columns]
            if node.group_by:
                node.group_by = [self.visit(expr) for expr in node.group_by]

            columns: dict[str, ast.Type] = {}
            base_field_names: set[str] = set()
            if isinstance(base_type, ast.SelectQueryAliasType):
                base_type = base_type.select_query_type
            if isinstance(base_type, ast.SelectSetQueryType):
                base_type = base_type.types[0]

            if isinstance(base_type, ast.SelectQueryType):
                columns = dict(base_type.columns)
                base_field_names = set(base_type.columns.keys())
            elif isinstance(base_type, ast.BaseTableType):
                base_field_names = set(base_type.resolve_database_table(self.context).get_asterisk().keys())
                for name in base_field_names:
                    columns[name] = ast.UnknownType()
            allowed_prefixes: set[str] = set()
            if isinstance(temp_join, ast.JoinExpr):
                if temp_join.alias is not None:
                    allowed_prefixes.add(temp_join.alias)
                if isinstance(temp_join.table, ast.Field) and temp_join.table.chain:
                    allowed_prefixes.add(str(temp_join.table.chain[0]))

            def ensure_pivot_column_valid(expr: ast.Expr) -> None:
                collector = FieldCollector()
                collector.visit(expr)
                for field in collector.fields:
                    if not field.chain:
                        raise QueryError("PIVOT columns must be identifiers")
                    if field.chain == ["*"]:
                        continue
                    if len(field.chain) == 1:
                        column_name = str(field.chain[0])
                    elif len(field.chain) == 2 and str(field.chain[0]) in allowed_prefixes:
                        column_name = str(field.chain[1])
                    else:
                        raise QueryError("PIVOT columns must be identifiers")
                    if base_field_names and column_name not in base_field_names:
                        raise QueryError(f'PIVOT column "{column_name}" was not found in the source table')

            for col in node.columns:
                ensure_pivot_column_valid(col.column)
            for agg in node.aggregates:
                ensure_pivot_column_valid(agg)
            if node.group_by:
                for expr in node.group_by:
                    ensure_pivot_column_valid(expr)

            node.type = ast.SelectQueryType(columns=columns)
            return node
        finally:
            self.scopes.pop()

    def visit_cte(self, node: ast.CTE):
        self.cte_counter += 1

        cte_expr = clone_expr(node.expr)

        if node.recursive and isinstance(cte_expr, ast.SelectSetQuery):
            # For recursive CTEs, resolve the base case first to determine column types,
            # then register the CTE so the recursive branch can self-reference it.
            base_select = clone_expr(cte_expr.initial_select_query)
            base_select = self.visit(base_select)

            placeholder = ast.CTE(
                name=node.name,
                expr=base_select,
                cte_type=node.cte_type,
                recursive=True,
                type=ast.CTETableType(name=node.name, select_query_type=base_select.type),
                materialized=node.materialized,
                using_key=node.using_key,
            )
            self.ctes[node.name] = placeholder

        cte_expr = self.visit(cte_expr)

        # If the CTE has a column name list, remap the type's columns
        if node.columns:
            if isinstance(cte_expr, ast.SelectQuery):
                if len(node.columns) != len(cte_expr.select):
                    raise QueryError(
                        f"CTE '{node.name}' has {len(cte_expr.select)} column(s) but {len(node.columns)} column name(s) were provided"
                    )

                # Remap the columns in the CTE's type to use the provided column names instead of the original ones.
                if cte_expr.type is not None:
                    cte_expr.type.columns = {
                        new_name: cte_expr.select[i].type or ast.UnknownType()
                        for i, new_name in enumerate(node.columns)
                    }
            elif isinstance(cte_expr, ast.SelectSetQuery):
                initial = cte_expr.initial_select_query
                while isinstance(initial, ast.SelectSetQuery):
                    initial = initial.initial_select_query
                if len(node.columns) != len(initial.select):
                    raise QueryError(
                        f"CTE '{node.name}' has {len(initial.select)} column(s) but {len(node.columns)} column name(s) were provided"
                    )

                # Remap the columns in the first type of the set query's type list.
                if cte_expr.type is not None:
                    first_type = cte_expr.type.types[0]
                    while isinstance(first_type, ast.SelectSetQueryType):
                        first_type = first_type.types[0]
                    first_type.columns = {
                        new_name: initial.select[i].type or ast.UnknownType() for i, new_name in enumerate(node.columns)
                    }

        if node.using_key is not None:
            if node.columns:
                valid_columns = set(node.columns)
            elif isinstance(cte_expr, ast.SelectQuery) and cte_expr.type:
                valid_columns = set(cte_expr.type.columns.keys())
            elif isinstance(cte_expr, ast.SelectSetQuery) and cte_expr.type:
                first_type = cte_expr.type.types[0]
                while isinstance(first_type, ast.SelectSetQueryType):
                    first_type = first_type.types[0]
                valid_columns = set(first_type.columns.keys())
            else:
                valid_columns = set()

            if valid_columns:
                invalid = [k for k in node.using_key if k not in valid_columns]
                if invalid:
                    raise QueryError(
                        f"USING KEY column(s) {', '.join(repr(k) for k in invalid)} not found in CTE '{node.name}'. "
                        f"Available columns: {', '.join(sorted(valid_columns))}"
                    )

        # Create a new CTE node instead of modifying the input
        # This ensures we can resolve CTEs even if they appear multiple times
        new_node = ast.CTE(
            start=node.start,
            end=node.end,
            type=ast.CTETableType(name=node.name, select_query_type=cast(ast.SelectQueryType, cte_expr.type)),
            name=node.name,
            expr=cte_expr,
            cte_type=node.cte_type,
            recursive=node.recursive,
            materialized=node.materialized,
            using_key=node.using_key,
            columns=node.columns,
        )

        self.cte_counter -= 1

        # Add this CTE to the current scope so subsequent CTEs can reference it
        self.ctes[node.name] = new_node

        return new_node

    def visit_select_query(self, node: ast.SelectQuery):
        """Visit each SELECT query or subquery."""
        if node.limit_with_ties and self.dialect == "postgres":
            raise QueryError("WITH TIES is not supported in postgres dialect")
        # This "SelectQueryType" is also a new scope for variables in the SELECT query.
        # We will add fields to it when we encounter them. This is used to resolve fields later.
        node_type = ast.SelectQueryType()

        parent_ctes = self.ctes

        # Track CTEs defined at this level (will be attached to new_node)
        current_level_ctes: dict[str, ast.CTE] | None = None

        # First step: resolve all the "WITH" CTEs onto "self.ctes" if there are any
        if node.ctes:
            self.ctes = dict(parent_ctes)
            current_level_ctes = {}
            for cte in node.ctes.values():
                resolved_cte = self.visit(cte)
                current_level_ctes[cte.name] = resolved_cte
            node_type.ctes = current_level_ctes
        else:
            self.ctes = dict(parent_ctes)

        # Append the "scope" onto the stack early, so that nodes we "self.visit" below can access it.
        self.scopes.append(node_type)

        # Clone the select query, piece by piece
        new_node = ast.SelectQuery(
            start=node.start,
            end=node.end,
            type=node_type,
            # Set CTEs only if they were defined at this level (use resolved CTEs)
            ctes=current_level_ctes,
            # "select" needs a default value, so [] it is
            select=[],
        )

        # Visit the FROM clauses first. This resolves all table aliases onto self.scopes[-1]
        new_node.select_from = self.visit(node.select_from)

        if node.limit_percent and self.dialect != "postgres":
            if self.dialect == "clickhouse":
                if not (isinstance(node.limit, ast.Constant) and isinstance(node.limit.value, (int, float))):
                    raise QueryError("LIMIT percent with expressions is not supported in clickhouse dialect")
            else:
                raise QueryError(f"LIMIT percent is not allowed in {self.dialect} dialect")
        # TODO: Consider constant folding to catch out-of-range percent expressions.
        if node.limit_percent and isinstance(node.limit, ast.Constant) and isinstance(node.limit.value, (int, float)):
            limit_value = float(node.limit.value)
            if limit_value < 0 or limit_value > 100:
                raise QueryError("Limit percent must be between 0 and 100")

        # Array joins (pass 1 - so we can use aliases from the array join in columns)
        new_node.array_join_op = node.array_join_op
        ac = AliasCollector()
        array_join_aliases = []
        if node.array_join_list:
            for expr in node.array_join_list:
                ac.visit(expr)
            array_join_aliases = ac.aliases
            for key in array_join_aliases:
                if key in node_type.aliases:
                    raise QueryError(f"Cannot redefine an alias with the name: {key}")
                node_type.aliases[key] = ast.FieldAliasType(alias=key, type=ast.UnknownType())

        # Visit all the "SELECT a,b,c" columns. Mark each for export in "columns".
        select_nodes = []
        for expr in node.select or []:
            if isinstance(expr, ast.SpreadExpr):
                raise QueryError("*COLUMNS(...) is not valid as a top-level SELECT item. Use COLUMNS(...) instead.")
            if isinstance(expr, ast.ColumnsExpr):
                expanded = self._columns_expr_exprs(expr)
                for col in expanded:
                    visited_col = self.visit(col)
                    select_nodes.append(visited_col)
                continue
            new_expr = self.visit(expr)
            if isinstance(new_expr.type, ast.AsteriskType):
                columns = self._asterisk_columns(new_expr.type, chain_prefix=new_expr.chain[:-1])
                for col in columns:
                    visited_col = self.visit(col)
                    if isinstance(visited_col, ast.Field):
                        visited_col.from_asterisk = True
                    elif isinstance(visited_col, ast.Alias) and isinstance(visited_col.expr, ast.Field):
                        visited_col.expr.from_asterisk = True
                    select_nodes.append(visited_col)
            else:
                select_nodes.append(new_expr)

        columns_with_visible_alias: dict[str, bool] = {}
        for new_expr in select_nodes:
            if isinstance(new_expr.type, ast.FieldAliasType):
                alias = new_expr.type.alias
            elif isinstance(new_expr.type, ast.FieldType):
                alias = new_expr.type.name
            elif isinstance(new_expr.type, ast.ExpressionFieldType):
                alias = new_expr.type.name
            elif isinstance(new_expr, ast.Alias):
                alias = new_expr.alias
            elif isinstance(new_expr.type, ast.CallType):
                from posthog.hogql.printer import print_prepared_ast

                alias = safe_identifier(print_prepared_ast(node=new_expr, context=self.context, dialect="hogql"))
            else:
                alias = None

            if alias:
                # Make a reference of the first visible or last hidden expr for each unique alias name.
                if isinstance(new_expr, ast.Alias) and new_expr.hidden:
                    if alias not in node_type.columns or not columns_with_visible_alias.get(alias, False):
                        node_type.columns[alias] = new_expr.type or ast.UnknownType()
                        columns_with_visible_alias[alias] = False
                else:
                    node_type.columns[alias] = new_expr.type or ast.UnknownType()
                    columns_with_visible_alias[alias] = True

            # add the column to the new select query
            new_node.select.append(new_expr)

        # Array joins (pass 2 - so we can use aliases from columns in the array join)
        if node.array_join_list:
            for key in array_join_aliases:
                if key in node_type.aliases:
                    # delete the keys we added in the first pass to avoid "can't redefine" errors
                    del node_type.aliases[key]
            new_node.array_join_list = [self.visit(expr) for expr in node.array_join_list]

        # :TRICKY: Make sure to clone and visit _all_ SelectQuery nodes.
        new_node.where = self.visit(node.where)
        new_node.prewhere = self.visit(node.prewhere)
        new_node.having = self.visit(node.having)
        new_node.qualify = self.visit(node.qualify)
        if node.group_by:
            new_node.group_by = [self.visit(expr) for expr in node.group_by]
        new_node.group_by_mode = node.group_by_mode
        if node.order_by:
            new_node.order_by = [self.visit(expr) for expr in node.order_by]
        if node.interpolate is not None:
            new_node.interpolate = [self.visit(expr) for expr in node.interpolate]
        new_node.limit_by = self.visit(node.limit_by)
        new_node.limit = self.visit(node.limit)
        new_node.limit_with_ties = node.limit_with_ties
        new_node.limit_percent = node.limit_percent
        new_node.offset = self.visit(node.offset)
        new_node.distinct = node.distinct
        new_node.window_exprs = (
            {name: self.visit(expr) for name, expr in node.window_exprs.items()} if node.window_exprs else None
        )
        new_node.settings = node.settings.model_copy() if node.settings is not None else None
        new_node.view_name = node.view_name

        self.scopes.pop()

        self.ctes = parent_ctes

        return new_node

    def _asterisk_columns(self, asterisk: ast.AsteriskType, chain_prefix: list[str]) -> list[ast.Field]:
        """Expand an asterisk. Mutates `select_query.select` and `select_query.type.columns` with the new fields.

        If we have a chain prefix (for example, in the case of a table alias), we prepend it to the chain of the new fields.
        """
        if isinstance(asterisk.table_type, ast.ColumnAliasedTableType):
            return [ast.Field(chain=[*chain_prefix, key]) for key in asterisk.table_type.alias_to_original]
        if isinstance(asterisk.table_type, ast.BaseTableType):
            table = asterisk.table_type.resolve_database_table(self.context)
            database_fields = table.get_asterisk()
            return [ast.Field(chain=[*chain_prefix, key]) for key in database_fields.keys()]
        elif (
            isinstance(asterisk.table_type, ast.SelectSetQueryType)
            or isinstance(asterisk.table_type, ast.SelectQueryType)
            or isinstance(asterisk.table_type, ast.SelectQueryAliasType)
        ):
            select = asterisk.table_type

            # Recursion because might be an `ast.BaseTableType` such as `ast.SelectViewType`
            if isinstance(select, ast.SelectQueryAliasType):
                return self._asterisk_columns(ast.AsteriskType(table_type=select.select_query_type), chain_prefix)

            if isinstance(select, ast.SelectSetQueryType):
                select = select.types[0]

            if isinstance(select, ast.SelectQueryType):
                return [ast.Field(chain=[*chain_prefix, key]) for key in select.columns.keys()]
            else:
                raise QueryError("Can't expand asterisk (*) on subquery")
        else:
            raise QueryError(f"Can't expand asterisk (*) on a type of type {type(asterisk.table_type).__name__}")

    def _columns_expr_exprs(self, node: ast.ColumnsExpr) -> list[ast.Expr]:
        """Expand a COLUMNS() expression into individual fields or expressions."""
        if node.all_columns:
            scope = self.scopes[-1]
            table_names = self._get_scope_table_names(scope)
            table_column_aliases = self._get_scope_table_column_aliases(scope)
            table_fields: list[tuple[Optional[str], ast.Expr]] = []
            excluded_entries: list[tuple[Optional[str], str]] = []

            for alias, table_type in scope.tables.items():
                asterisk_type = ast.AsteriskType(table_type=table_type)
                try:
                    raw_fields = self._asterisk_columns(asterisk_type, chain_prefix=[])
                except QueryError:
                    continue
                resolved_fields: list[ast.Expr] = list(raw_fields)
                # For ColumnAliasedTableType, _asterisk_columns already returns
                # aliased names. Only apply manual remapping for other types.
                if not isinstance(table_type, ast.ColumnAliasedTableType):
                    column_aliases = table_column_aliases.get(alias)
                    if column_aliases:
                        resolved_fields = self._apply_column_aliases(resolved_fields, column_aliases)
                for field in resolved_fields:
                    table_fields.append((alias, field))

            for table_type in scope.anonymous_tables:
                asterisk_type = ast.AsteriskType(table_type=table_type)
                try:
                    all_fields = self._asterisk_columns(asterisk_type, chain_prefix=[])
                except QueryError:
                    continue
                for field in all_fields:
                    table_fields.append((None, field))

            if node.exclude:
                remaining_fields = list(table_fields)
                for raw_name in node.exclude:
                    name = str(raw_name)
                    parts = name.split(".")
                    column_name = parts[-1]
                    qualifier = ".".join(parts[:-1]) if len(parts) > 1 else None
                    excluded_entries.append((qualifier, column_name))

                    if len(parts) > 1:
                        qualifier = ".".join(parts[:-1])
                        candidate_aliases = [
                            alias
                            for alias in scope.tables.keys()
                            if alias == qualifier or table_names.get(alias) == qualifier
                        ]

                        if not candidate_aliases:
                            raise QueryError(f'Column "{column_name}" in EXCLUDE list was not found in {qualifier}')

                        found = False
                        filtered_fields: list[tuple[Optional[str], ast.Expr]] = []
                        for tbl_alias, tbl_field in remaining_fields:
                            field_name = str(tbl_field.chain[-1]) if isinstance(tbl_field, ast.Field) else None
                            if tbl_alias in candidate_aliases and field_name == column_name:
                                found = True
                                continue
                            filtered_fields.append((tbl_alias, tbl_field))

                        if not found:
                            raise QueryError(f'Column "{column_name}" in EXCLUDE list was not found in {qualifier}')

                        remaining_fields = filtered_fields
                        continue

                    unqualified_filtered: list[tuple[Optional[str], ast.Expr]] = []
                    found = False
                    for tbl_alias, tbl_field in remaining_fields:
                        field_name = str(tbl_field.chain[-1]) if isinstance(tbl_field, ast.Field) else None
                        if field_name == column_name:
                            found = True
                            continue
                        unqualified_filtered.append((tbl_alias, tbl_field))

                    if not found:
                        if len(scope.tables) == 1 and len(scope.anonymous_tables) == 0:
                            [only_alias] = list(scope.tables.keys())
                            table_label = table_names.get(only_alias, only_alias)
                        else:
                            table_label = "the selected tables"
                        raise QueryError(f'Column "{column_name}" in EXCLUDE list was not found in {table_label}')

                    remaining_fields = unqualified_filtered

                table_fields = remaining_fields

            if node.replace:
                excluded_column_names = {column_name for _, column_name in excluded_entries}
                for replace_name in node.replace.keys():
                    if replace_name in excluded_column_names:
                        raise QueryError(f'Column "{replace_name}" cannot occur in both EXCLUDE and REPLACE list')

                def matches_excluded(field: ast.Field) -> Optional[str]:
                    if not all(isinstance(part, str) for part in field.chain):
                        return None
                    column_name = cast(str, field.chain[-1])
                    qualifier = ".".join(cast(list[str], field.chain[:-1])) if len(field.chain) > 1 else None
                    for excluded_qualifier, excluded_column in excluded_entries:
                        if excluded_column != column_name:
                            continue
                        if excluded_qualifier is None:
                            return column_name
                        candidate_aliases = [
                            alias
                            for alias in scope.tables.keys()
                            if alias == excluded_qualifier or table_names.get(alias) == excluded_qualifier
                        ]
                        if qualifier in candidate_aliases:
                            return column_name
                    return None

                for replace_name, replace_expr in node.replace.items():
                    collector = FieldCollector()
                    collector.visit(replace_expr)
                    for field in collector.fields:
                        excluded_match = matches_excluded(field)
                        if excluded_match is not None:
                            raise QueryError(
                                f'Replace expression for "{replace_name}" cannot reference excluded column "{excluded_match}"'
                            )

                replace_match_counts = dict.fromkeys(node.replace.keys(), 0)
                replaced_fields: list[tuple[Optional[str], ast.Expr]] = []
                for tbl_alias, tbl_field in table_fields:
                    field_name = str(tbl_field.chain[-1]) if isinstance(tbl_field, ast.Field) else None
                    if field_name is not None and field_name in node.replace:
                        replacement = clone_expr(node.replace[field_name])
                        replace_match_counts[field_name] += 1
                        replaced_fields.append((tbl_alias, ast.Alias(expr=replacement, alias=field_name)))
                    else:
                        replaced_fields.append((tbl_alias, tbl_field))

                missing = [name for name, count in replace_match_counts.items() if count == 0]
                if missing:
                    if len(scope.tables) == 1 and len(scope.anonymous_tables) == 0:
                        [only_alias] = list(scope.tables.keys())
                        table_label = table_names.get(only_alias, only_alias)
                    else:
                        table_label = "the selected tables"
                    raise QueryError(f'Column "{missing[0]}" in REPLACE list was not found in {table_label}')

                table_fields = replaced_fields

            matched_fields = [field for _, field in table_fields]
            if not matched_fields:
                raise QueryError("No columns matched the EXCLUDE list")
            return matched_fields

        if node.columns is not None:
            return list(node.columns)

        regex = node.regex or ""
        try:
            pattern = re2.compile(regex)
        except re2.error as e:
            raise QueryError(f"COLUMNS() has an invalid regex pattern: {e}")
        scope = self.scopes[-1]
        all_table_types: list[ast.TableOrSelectType] = list(scope.tables.values()) + list(scope.anonymous_tables)
        regex_matched_fields: list[ast.Expr] = []
        for table_type in all_table_types:
            asterisk_type = ast.AsteriskType(table_type=table_type)
            try:
                all_fields = self._asterisk_columns(asterisk_type, chain_prefix=[])
            except QueryError:
                continue
            for field in all_fields:
                col_name = field.chain[-1] if isinstance(field.chain[-1], str) else str(field.chain[-1])
                if pattern.search(col_name):
                    regex_matched_fields.append(field)
        if not regex_matched_fields:
            raise QueryError(f"No columns matched the COLUMNS('{node.regex}') expression")
        return regex_matched_fields

    def _apply_column_aliases(self, fields: list[ast.Expr], column_aliases: list[str]) -> list[ast.Expr]:
        if not column_aliases:
            return fields

        aliased_fields: list[ast.Expr] = []
        for index, field in enumerate(fields):
            if index >= len(column_aliases):
                aliased_fields.append(field)
                continue
            if not isinstance(field, ast.Field):
                aliased_fields.append(field)
                continue
            aliased = cast(ast.Field, clone_expr(field))
            aliased.chain = [*aliased.chain[:-1], column_aliases[index]]
            aliased_fields.append(aliased)

        return aliased_fields

    def visit_join_expr(self, node: ast.JoinExpr):
        """Visit each FROM and JOIN table or subquery."""

        if len(self.scopes) == 0:
            raise ImpossibleASTError("Unexpected JoinExpr outside a SELECT query")

        scope = self._get_scope()

        if isinstance(node.table, ast.HogQLXTag):
            node.table = expand_hogqlx_query(node.table, self.context.team_id)

        if isinstance(node.table, ast.Field):
            table_name_chain = [str(n) for n in node.table.chain]
            table_name_alias = "__".join(table_name_chain)
            table_alias: str = node.alias or table_name_alias
            if table_alias in scope.tables:
                raise QueryError(f'Already have joined a table called "{table_alias}". Can\'t redefine.')

            cte_table = self.ctes.get(".".join(table_name_chain))
            if cte_table:
                assert isinstance(cte_table.expr.type, ast.SelectQueryType | ast.SelectSetQueryType)
                # Use CTETableType so that fields are properly qualified with the CTE name when printed
                cte_table_type = ast.CTETableType(name=cte_table.name, select_query_type=cte_table.expr.type)
                node_type: ast.TableOrSelectType = cte_table_type
                if table_alias != table_name_alias:
                    # Use CTETableAliasType for aliased CTEs (e.g., FROM my_cte AS alias)
                    node_type = ast.CTETableAliasType(alias=table_alias, cte_table_type=cte_table_type)

                node = cast(ast.JoinExpr, clone_expr(node))
                if node.constraint and node.constraint.constraint_type == "USING":
                    # visit USING constraint before adding the table to avoid ambiguous names
                    node.constraint = self.visit_join_constraint(node.constraint)

                scope.tables[table_alias or cte_table.name] = node_type
                scope_table_names = self._get_scope_table_names(scope)
                scope_table_names[table_alias or cte_table.name] = cte_table.name
                if node.column_aliases:
                    scope_table_column_aliases = self._get_scope_table_column_aliases(scope)
                    scope_table_column_aliases[table_alias or cte_table.name] = node.column_aliases

                # :TRICKY: Make sure to clone and visit _all_ JoinExpr fields/nodes.
                node.type = node_type
                node.table = clone_expr(cast(ast.Field, node.table))
                node.table.type = cte_table_type
                node.next_join = self.visit(node.next_join)
                node.alias = table_alias

                if node.constraint and node.constraint.constraint_type == "ON":
                    node.constraint = self.visit_join_constraint(node.constraint)
                node.sample = self.visit(node.sample)

                return node

            database_table = cast(Database, self.database).get_table(table_name_chain)

            if isinstance(database_table, SavedQuery):
                self.current_view_depth += 1

                node.table = parse_select(str(database_table.query))

                if isinstance(node.table, ast.SelectQuery):
                    node.table.view_name = database_table.name

                node.alias = table_alias or database_table.name
                node = self.visit(node)

                self.current_view_depth -= 1
                return node

            if isinstance(database_table, LazyTable):
                if isinstance(database_table, PersonsTable):
                    # Check for inlineable exprs in the join on the persons table
                    database_table = database_table.create_new_table_with_filter(node)
                node_table_type: ast.TableType | ast.LazyTableType = ast.LazyTableType(table=database_table)

            else:
                assert isinstance(database_table, ast.Table)
                node_table_type = ast.TableType(table=database_table)

            # Always add an alias for function call tables. This way `select table.* from table` is replaced with
            # `select table.* from something() as table`, and not with `select something().* from something()`.
            if node.column_aliases:
                # Build alias→original mapping from the table's visible columns
                asterisk_fields = list(database_table.get_asterisk().keys())
                if len(node.column_aliases) > len(asterisk_fields):
                    raise QueryError(
                        f"Table has {len(asterisk_fields)} column(s) available for aliasing "
                        f"but {len(node.column_aliases)} alias(es) were provided"
                    )
                seen_aliases: set[str] = set()
                for alias_name in node.column_aliases:
                    if alias_name in seen_aliases:
                        raise QueryError(f"Duplicate column alias '{alias_name}' in table alias '{table_alias}'")
                    seen_aliases.add(alias_name)
                alias_to_original: dict[str, str] = {}
                aliased_originals = set()
                for alias_name, orig_name in zip(node.column_aliases, asterisk_fields):
                    alias_to_original[alias_name] = orig_name
                    aliased_originals.add(orig_name)
                # Remaining columns keep their original names, unless
                # their name collides with an already-defined alias.
                for orig_name in asterisk_fields:
                    if orig_name not in aliased_originals and orig_name not in alias_to_original:
                        alias_to_original[orig_name] = orig_name
                node_type = ast.ColumnAliasedTableType(
                    alias=table_alias, table_type=node_table_type, alias_to_original=alias_to_original
                )
            elif table_alias != table_name_alias or isinstance(database_table, FunctionCallTable):
                node_type = ast.TableAliasType(alias=table_alias, table_type=node_table_type)
            else:
                node_type = node_table_type

            node = cast(ast.JoinExpr, clone_expr(node))
            if node.constraint and node.constraint.constraint_type == "USING":
                # visit USING constraint before adding the table to avoid ambiguous names
                node.constraint = self.visit_join_constraint(node.constraint)

            scope.tables[table_alias] = node_type
            scope_table_names = self._get_scope_table_names(scope)
            scope_table_names[table_alias] = ".".join(table_name_chain)
            if node.column_aliases and not isinstance(node_type, ast.ColumnAliasedTableType):
                scope_table_column_aliases = self._get_scope_table_column_aliases(scope)
                scope_table_column_aliases[table_alias] = node.column_aliases

            # :TRICKY: Make sure to clone and visit _all_ JoinExpr fields/nodes.
            node.type = node_type
            assert node.table is not None

            node.table = cast(ast.Field, clone_expr(node.table))
            node.table.type = node_table_type
            if node.table_args is not None:
                node.table_args = [self.visit(arg) for arg in node.table_args]
            node.next_join = self.visit(node.next_join)

            # Look ahead if current is events table and next is s3 table, global join must be used for distributed query on external data to work
            if USE_GLOBAL_JOINS:
                global_table: ast.TableType | None = None

                if isinstance(node.type, (ast.TableAliasType, ast.ColumnAliasedTableType)) and isinstance(
                    node.type.table_type, ast.TableType
                ):
                    global_table = node.type.table_type
                elif isinstance(node.type, ast.TableType):
                    global_table = node.type

                if global_table and isinstance(global_table.table, EventsTable):
                    next_join = node.next_join
                    is_global = False

                    while next_join:
                        if self._is_next_s3(next_join):
                            is_global = True
                        # Use GLOBAL joins for nested subqueries for S3 tables until https://github.com/ClickHouse/ClickHouse/pull/85839 is in
                        elif isinstance(next_join.type, ast.SelectQueryAliasType):
                            select_query_type = next_join.type.select_query_type
                            tables = self._extract_tables_from_query_type(select_query_type)
                            if any(self._is_s3_table(table) for table in tables):
                                is_global = True

                        next_join = next_join.next_join

                    # If there exists a S3 table in the chain, then all joins require to be a GLOBAL join
                    if is_global:
                        next_join = node.next_join
                        while next_join:
                            next_join.join_type = f"GLOBAL {next_join.join_type}"
                            next_join = next_join.next_join

            if node.constraint and node.constraint.constraint_type == "ON":
                node.constraint = self.visit_join_constraint(node.constraint)
            node.sample = self.visit(node.sample)

            # In case we had a function call table, and had to add an alias where none was present, mark it here
            if isinstance(node_type, (ast.TableAliasType, ast.ColumnAliasedTableType)) and node.alias is None:
                node.alias = node_type.alias

            return node

        elif isinstance(node.table, ast.SelectQuery) or isinstance(node.table, ast.SelectSetQuery):
            node = cast(ast.JoinExpr, clone_expr(node))
            if node.constraint and node.constraint.constraint_type == "USING":
                # visit USING constraint before adding the table to avoid ambiguous names
                node.constraint = self.visit_join_constraint(node.constraint)

            node.table = cast(ast.SelectQuery, super().visit(node.table))

            # Remap column names if column_aliases is provided (e.g. AS v(id, name))
            if node.column_aliases and node.table.type:
                # Find the SelectQuery to count columns from the select list
                inner_select: ast.SelectQuery | ast.SelectSetQuery = node.table
                if isinstance(inner_select, ast.SelectSetQuery):
                    inner = inner_select.initial_select_query
                    while isinstance(inner, ast.SelectSetQuery):
                        inner = inner.initial_select_query
                    inner_select = inner

                num_cols = len(cast(ast.SelectQuery, inner_select).select)
                if len(node.column_aliases) != num_cols:
                    raise QueryError(
                        f"Subquery has {num_cols} column(s) but {len(node.column_aliases)} column name(s) were provided"
                    )

                # Remap the SelectQueryType columns dict
                select_query_type = cast(ast.SelectQueryType, node.table.type)
                if isinstance(node.table.type, ast.SelectSetQueryType):
                    first_type = node.table.type.types[0]
                    while isinstance(first_type, ast.SelectSetQueryType):
                        first_type = first_type.types[0]
                    select_query_type = cast(ast.SelectQueryType, first_type)

                # Build new columns from the select list's types, keyed by the alias column names
                select_list = cast(ast.SelectQuery, inner_select).select
                select_query_type.columns = {
                    new_name: (expr.type if expr.type is not None else ast.UnknownType())
                    for new_name, expr in zip(node.column_aliases, select_list)
                }

                # For non-postgres dialects, bake column aliases into the inner
                # SELECT as AS aliases so ClickHouse/HogQL (which don't support
                # the ``AS t(col1, col2)`` syntax) get correct column names.
                if self.dialect != "postgres":
                    inner_query = cast(ast.SelectQuery, inner_select)
                    new_select: list[ast.Expr] = []
                    for i, expr in enumerate(inner_query.select):
                        if i < len(node.column_aliases):
                            alias_name = node.column_aliases[i]
                            # Avoid wrapping if the expression is already aliased with the same name
                            if isinstance(expr, ast.Alias) and expr.alias == alias_name:
                                new_select.append(expr)
                            else:
                                new_select.append(ast.Alias(alias=alias_name, expr=expr, type=expr.type))
                        else:
                            new_select.append(expr)
                    inner_query.select = new_select
                    node.column_aliases = None

            if isinstance(node.table, ast.SelectQuery) and node.table.view_name is not None and node.alias is not None:
                if node.alias in scope.tables:
                    raise QueryError(
                        f'Already have joined a table called "{node.alias}". Can\'t join another one with the same name.'
                    )
                node.type = ast.SelectViewType(
                    alias=node.alias,
                    view_name=node.table.view_name,
                    select_query_type=cast(ast.SelectQueryType, node.table.type),
                )
                scope.tables[node.alias] = node.type
            elif node.alias is not None:
                if node.alias in scope.tables:
                    raise QueryError(
                        f'Already have joined a table called "{node.alias}". Can\'t join another one with the same name.'
                    )
                node.type = ast.SelectQueryAliasType(
                    alias=node.alias, select_query_type=cast(ast.SelectQueryType, node.table.type)
                )
                scope.tables[node.alias] = node.type
            else:
                node.type = cast(ast.TableOrSelectType, node.table.type)
                scope.anonymous_tables.append(cast(ast.SelectQueryType | ast.SelectSetQueryType, node.type))

            # :TRICKY: Make sure to clone and visit _all_ JoinExpr fields/nodes.
            node.next_join = self.visit(node.next_join)
            if node.constraint and node.constraint.constraint_type == "ON":
                node.constraint = self.visit_join_constraint(node.constraint)
            node.sample = self.visit(node.sample)

            return node

        elif isinstance(node.table, ast.ValuesQuery):
            node = cast(ast.JoinExpr, clone_expr(node))
            node.table = cast(ast.ValuesQuery, self.visit(node.table))

            # Auto-generate alias and column_aliases when omitted so the
            # printed SQL contains column names that match the resolved
            # SelectQueryType (sugar syntax like DuckDB's col0, col1, ...).
            if not node.column_aliases and node.table.type:
                node.column_aliases = list(node.table.type.columns.keys())
                if node.alias is None:
                    node.alias = "values"

            # Remap column names if column_aliases is provided
            if node.column_aliases and node.table.type:
                num_cols = len(node.table.type.columns)
                if len(node.column_aliases) != num_cols:
                    raise QueryError(
                        f"VALUES has {num_cols} column(s) but {len(node.column_aliases)} column name(s) were provided"
                    )
                original_columns = node.table.type.columns
                node.table.type.columns = {
                    new_name: list(original_columns.values())[i] for i, new_name in enumerate(node.column_aliases)
                }

            if node.alias is not None:
                if node.alias in scope.tables:
                    raise QueryError(
                        f'Already have joined a table called "{node.alias}". Can\'t join another one with the same name.'
                    )
                node.type = ast.SelectQueryAliasType(
                    alias=node.alias, select_query_type=cast(ast.SelectQueryType, node.table.type)
                )
                scope.tables[node.alias] = node.type
            else:
                node.type = cast(ast.TableOrSelectType, node.table.type)
                scope.anonymous_tables.append(cast(ast.SelectQueryType, node.type))

            node.next_join = self.visit(node.next_join)
            if node.constraint and node.constraint.constraint_type == "ON":
                node.constraint = self.visit_join_constraint(node.constraint)
            node.sample = self.visit(node.sample)

            return node

        elif isinstance(node.table, ast.UnpivotExpr):
            node = cast(ast.JoinExpr, clone_expr(node))
            if node.constraint and node.constraint.constraint_type == "USING":
                node.constraint = self.visit_join_constraint(node.constraint)

            node.table = cast(ast.UnpivotExpr, self.visit(node.table))

            if node.alias is not None:
                if node.alias in scope.tables:
                    raise QueryError(
                        f'Already have joined a table called "{node.alias}". Can\'t join another one with the same name.'
                    )
                node.type = ast.SelectQueryAliasType(
                    alias=node.alias, select_query_type=cast(ast.SelectQueryType, node.table.type)
                )
                scope.tables[node.alias] = node.type
            else:
                node.type = cast(ast.TableOrSelectType, node.table.type)
                scope.anonymous_tables.append(cast(ast.SelectQueryType, node.type))

            node.next_join = self.visit(node.next_join)
            if node.constraint and node.constraint.constraint_type == "ON":
                node.constraint = self.visit_join_constraint(node.constraint)
            node.sample = self.visit(node.sample)

            return node
        elif isinstance(node.table, ast.PivotExpr):
            node = cast(ast.JoinExpr, clone_expr(node))
            if node.constraint and node.constraint.constraint_type == "USING":
                node.constraint = self.visit_join_constraint(node.constraint)

            node.table = cast(ast.PivotExpr, self.visit(node.table))

            if node.alias is not None:
                if node.alias in scope.tables:
                    raise QueryError(
                        f'Already have joined a table called "{node.alias}". Can\'t join another one with the same name.'
                    )
                node.type = ast.SelectQueryAliasType(
                    alias=node.alias, select_query_type=cast(ast.SelectQueryType, node.table.type)
                )
                scope.tables[node.alias] = node.type
            else:
                node.type = cast(ast.TableOrSelectType, node.table.type)
                scope.anonymous_tables.append(cast(ast.SelectQueryType, node.type))

            node.next_join = self.visit(node.next_join)
            if node.constraint and node.constraint.constraint_type == "ON":
                node.constraint = self.visit_join_constraint(node.constraint)
            node.sample = self.visit(node.sample)

            return node
        else:
            raise QueryError(f"A {type(node.table).__name__} cannot be used as a SELECT source")

    def visit_hogqlx_tag(self, node: ast.HogQLXTag):
        if node.kind in HOGQLX_TAGS or node.kind in HOGQLX_COMPONENTS:
            return self.visit(convert_to_hx(node))
        return self.visit(expand_hogqlx_query(node, self.context.team_id))

    def visit_alias(self, node: ast.Alias):
        """Visit column aliases. SELECT 1, (select 3 as y) as x."""
        if len(self.scopes) == 0:
            raise QueryError("Aliases are allowed only within SELECT queries")

        scope = self._get_scope()
        if node.alias in scope.aliases and not node.hidden:
            raise QueryError(f"Cannot redefine an alias with the name: {node.alias}")
        if node.alias == "":
            raise ImpossibleASTError("Alias cannot be empty")

        node = super().visit_alias(node)
        node.type = ast.FieldAliasType(alias=node.alias, type=node.expr.type or ast.UnknownType())
        if not node.hidden:
            scope.aliases[node.alias] = node.type
        return node

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation):
        node = super().visit_arithmetic_operation(node)

        if node.left.type is None or node.right.type is None:
            return node

        left_type = node.left.type.resolve_constant_type(self.context)
        right_type = node.right.type.resolve_constant_type(self.context)

        if isinstance(left_type, ast.IntegerType) and isinstance(right_type, ast.IntegerType):
            node.type = ast.IntegerType()
        elif isinstance(left_type, ast.FloatType) and isinstance(right_type, ast.FloatType):
            node.type = ast.FloatType()
        elif isinstance(left_type, ast.IntegerType) and isinstance(right_type, ast.FloatType):
            node.type = ast.FloatType()
        elif isinstance(left_type, ast.FloatType) and isinstance(right_type, ast.IntegerType):
            node.type = ast.FloatType()
        elif isinstance(left_type, ast.DateTimeType) or isinstance(right_type, ast.DateTimeType):
            node.type = ast.DateTimeType()
        elif isinstance(left_type, ast.UnknownType) or isinstance(right_type, ast.UnknownType):
            node.type = ast.UnknownType()
        else:
            node.type = ast.UnknownType()

        node.type.nullable = left_type.nullable or right_type.nullable
        return node

    def visit_call(self, node: ast.Call):
        """Visit function calls."""

        # Expand *COLUMNS(...) in function arguments
        expanded_args: list[ast.Expr] = []
        has_spread = False
        for arg in node.args:
            if isinstance(arg, ast.SpreadExpr) and isinstance(arg.expr, ast.ColumnsExpr):
                expanded_args.extend(self._columns_expr_exprs(arg.expr))
                has_spread = True
            else:
                expanded_args.append(arg)
        if has_spread:
            node = ast.Call(
                name=node.name,
                args=expanded_args,
                params=node.params,
                distinct=node.distinct,
                start=node.start,
                end=node.end,
            )

        if func_meta := find_hogql_posthog_function(node.name):
            validate_function_args(node.args, func_meta.min_args, func_meta.max_args, node.name)

            if node.name == "sparkline":
                return self.visit(sparkline(node=node, args=node.args))
            if node.name == "recordingButton":
                return self.visit(recording_button(node=node, args=node.args))
            if node.name == "explainCSPReport":
                return self.visit(explain_csp_report(node=node, args=node.args))
            if node.name == "matchesAction":
                events_alias, _ = self._get_events_table_current_scope()
                if events_alias is None:
                    raise QueryError("matchesAction can only be used with the events table")
                return self.visit(
                    matches_action(node=node, args=node.args, context=self.context, events_alias=events_alias)
                )
            if node.name == "getSurveyResponse":
                return self.visit(get_survey_response(node=node, args=node.args))
            if node.name == "uniqueSurveySubmissionsFilter":
                return self.visit(
                    unique_survey_submissions_filter(node=node, args=node.args, team_id=self.context.team_id)
                )
            if node.name == "__preview_getTrafficType":
                return self.visit(get_traffic_type(node=node, args=node.args))
            if node.name == "__preview_getTrafficCategory":
                return self.visit(get_traffic_category(node=node, args=node.args))
            if node.name == "__preview_isBot":
                return self.visit(is_bot(node=node, args=node.args))
            if node.name == "__preview_getBotType":
                return self.visit(get_bot_type(node=node, args=node.args))
            if node.name == "__preview_getBotName":
                return self.visit(get_bot_name(node=node, args=node.args))

        node = super().visit_call(node)
        arg_types: list[ast.ConstantType] = []
        for arg in node.args:
            if arg.type:
                arg_types.append(arg.type.resolve_constant_type(self.context))
            else:
                arg_types.append(ast.UnknownType())
        param_types: Optional[list[ast.ConstantType]] = None
        if node.params is not None:
            param_types = []
            for i, param in enumerate(node.params):
                if param.type:
                    param_types.append(param.type.resolve_constant_type(self.context))
                else:
                    raise ResolutionError(f"Unknown type for function '{node.name}', parameter {i}")

        return_type = None

        if func_meta := HOGQL_CLICKHOUSE_FUNCTIONS.get(node.name, None):
            if signatures := func_meta.signatures:
                for sig_arg_types, sig_return_type in signatures:
                    if sig_arg_types is None or compare_types(arg_types, sig_arg_types, args=node.args):
                        return_type = dataclasses.replace(sig_return_type)
                        break

        if return_type is None:
            return_type = ast.UnknownType()

            # Uncomment once all hogql mappings are complete with signatures
            # arg_type_classes = [arg_type.__class__.__name__ for arg_type in arg_types]
            # raise ResolutionError(
            #     f"Can't call function '{node.name}' with arguments of type: {', '.join(arg_type_classes)}"
            # )

        if node.name == "concat":
            return_type.nullable = False  # valid only if at least 1 param is not null
        elif not isinstance(return_type, ast.UnknownType):  # why cannot we set nullability here?
            return_type.nullable = any(arg_type.nullable for arg_type in arg_types)

        if node.name.lower() in ("nullif", "tonullable") or node.name.lower().endswith("ornull"):
            return_type.nullable = True
        elif node.name.lower() == "assumenotnull":
            return_type.nullable = False

        node.type = ast.CallType(
            name=node.name,
            arg_types=arg_types,
            param_types=param_types,
            return_type=return_type,
        )
        return node

    def visit_expr_call(self, node: ast.ExprCall):
        raise QueryError("You can only call simple functions in HogQL, not expressions")

    def visit_block(self, node: ast.Block):
        raise QueryError("You can not use blocks in HogQL")

    def visit_lambda(self, node: ast.Lambda):
        """Visit each SELECT query or subquery."""
        # Each Lambda is a new scope in field name resolution.
        # This type keeps track of all lambda arguments that are in scope.
        node_type = ast.SelectQueryType(parent=self.scopes[-1] if len(self.scopes) > 0 else None, is_lambda_type=True)

        for arg in node.args:
            node_type.aliases[arg] = ast.FieldAliasType(alias=arg, type=ast.LambdaArgumentType(name=arg))

        self.scopes.append(node_type)

        new_node = cast(ast.Lambda, clone_expr(node))
        new_node.type = node_type
        new_node.expr = self.visit(new_node.expr)

        self.scopes.pop()

        return new_node

    def visit_try_cast(self, node: ast.TryCast):
        if self.dialect != "postgres":
            raise QueryError(f"TRY_CAST is not allowed in {self.dialect} dialect")
        node = cast(ast.TryCast, clone_expr(node))
        node.expr = self.visit(node.expr)
        return node

    def visit_positional_ref(self, node: ast.PositionalRef):
        if self.dialect != "postgres":
            raise QueryError(f"Positional references are not allowed in {self.dialect} dialect")
        node = cast(ast.PositionalRef, clone_expr(node))
        node.type = ast.UnknownType()
        return node

    def visit_array_slice(self, node: ast.ArraySlice):
        if self.dialect not in {"postgres", "clickhouse"}:
            raise QueryError(f"Array slices are not allowed in {self.dialect} dialect")
        node = cast(ast.ArraySlice, clone_expr(node))
        node.array = self.visit(node.array)
        if node.start_expr is not None:
            node.start_expr = self.visit(node.start_expr)
        if node.end_expr is not None:
            node.end_expr = self.visit(node.end_expr)
        return node

    def visit_field(self, node: ast.Field):
        """Visit a field such as ast.Field(chain=["e", "properties", "$browser"])"""
        if len(node.chain) == 0:
            raise ResolutionError("Invalid field access with empty chain")

        scope = self._get_scope()
        name = str(node.chain[0])

        if self.dialect == "postgres" and len(node.chain) == 1:
            keyword = name.lower()
            if keyword in POSTGRES_KEYWORD_TYPES and name not in scope.columns and name not in scope.aliases:
                keyword_type = POSTGRES_KEYWORD_TYPES[keyword]
                return ast.Keyword(
                    name=keyword,
                    type=keyword_type(nullable=False),
                    start=node.start,
                    end=node.end,
                )

        # Apply virtual property mapping before field resolution
        node = map_virtual_properties(node)

        node = super().visit_field(node)
        name = str(node.chain[0])

        # Only look for fields in the last SELECT scope, instead of all previous select queries.
        # That's because ClickHouse does not support subqueries accessing "x.event". This is forbidden:
        # - "SELECT event, (select count() from events where event = x.event) as c FROM events x where event = '$pageview'",
        # But this is supported:
        # - "SELECT t.big_count FROM (select count() + 100 as big_count from events) as t JOIN events e ON (e.event = t.event)",
        type: Optional[ast.Type] = None

        # If the field contains at least two parts, the first might be a table.
        type = lookup_table_by_name(scope, self.ctes, node)

        # If it's a wildcard
        if name == "*" and len(node.chain) == 1:
            table_count = len(scope.anonymous_tables) + len(scope.tables)
            if table_count == 0:
                raise QueryError("Cannot use '*' when there are no tables in the query")
            if table_count > 1:
                raise QueryError("Cannot use '*' without table name when there are multiple tables in the query")
            table_type = (
                scope.anonymous_tables[0] if len(scope.anonymous_tables) > 0 else next(iter(scope.tables.values()))
            )
            type = ast.AsteriskType(table_type=table_type)

        # Field in scope
        if (
            not type
            and len(node.chain) == 1
            and self.dialect == "postgres"
            and name.lower() in POSTGRES_KEYWORD_TYPES
            and name in scope.columns
        ):
            type = scope.get_child(name, self.context)

        if not type:
            type = lookup_field_by_name(scope, name, self.context)

        # If scope is a lambda, check with the parent scope
        if not type and scope.is_lambda_type and len(self.scopes) > 1:
            type = lookup_table_by_name(self.scopes[-2], self.ctes, node)

            if not type:
                type = lookup_field_by_name(self.scopes[-2], name, self.context)

        if not type:
            cte = self.ctes.get(name, None)
            if cte:
                if len(node.chain) > 1:
                    raise QueryError(f"Cannot access fields on CTE {name} yet")

                assert isinstance(cte.type, ast.CTETableType)

                # Check if this is a table CTE (subquery style) vs scalar CTE (column style)
                # Table CTE: WITH x AS (SELECT ...) - can only be used in FROM clauses
                # Scalar CTE: WITH expr AS x or WITH (SELECT 1) AS x - can be used as scalar values
                if cte.cte_type == "subquery":
                    # Table CTE: can only be used in FROM clauses (handled in visit_join_expr)
                    raise QueryError(f"Cannot use table CTE {cte.name} as a value. Use it in a FROM clause instead.")
                elif cte.cte_type == "column":
                    # Try to extract the actual return type from the scalar CTE's SELECT query
                    # Scalar CTEs should return a single column, so we get the type of the first selected column
                    inner_type: ast.Type = ast.StringType()
                    if isinstance(cte.type.select_query_type, ast.SelectQueryType):
                        select_query_type = cte.type.select_query_type
                        if select_query_type.columns:
                            # Get the type of the first (and should be only) column
                            first_column_type = next(iter(select_query_type.columns.values()), None)
                            if first_column_type is not None:
                                inner_type = first_column_type

                    return ast.Field(chain=node.chain, type=ast.FieldAliasType(alias=name, type=inner_type))
                else:
                    raise ImpossibleASTError(f"Cannot use CTE {cte.name} as a value. Use it in a FROM clause instead.")

        if not type:
            if self.context.globals is not None and name in self.context.globals:
                parsed_chain: list[str] = []
                value: Any = self.context.globals
                for link in node.chain:
                    parsed_chain.append(str(link))
                    if isinstance(value, dict):
                        value = value.get(str(link), None)
                    elif isinstance(value, list):
                        try:
                            value = value[int(link)]
                        except (ValueError, IndexError):
                            raise QueryError(f"Cannot resolve field: {'.'.join(parsed_chain)}")
                    else:
                        raise QueryError(f"Cannot resolve field: {'.'.join(parsed_chain)}")
                global_type = resolve_constant_data_type(value)
                if global_type:
                    self.context.add_notice(
                        start=node.start,
                        end=node.end,
                        message=f"Field '{'.'.join([str(c) for c in node.chain])}' is of type '{global_type.print_type()}'",
                    )
                return ast.Constant(value=value, type=global_type)

            if self.dialect == "clickhouse":
                # To debug, add a breakpoint() here and print self.context.database
                #
                # from rich.pretty import pprint
                # pprint(self.context.database, max_depth=3)
                # breakpoint()
                #
                # One likely cause is that the database context isn't set up as you
                # expect it to be.
                raise QueryError(f"Unable to resolve field: {name}")
            else:
                type = ast.UnresolvedFieldType(name=name)
                self.context.add_error(
                    start=node.start,
                    end=node.end,
                    message=f"Unable to resolve field: {name}",
                )

        # Recursively resolve the rest of the chain until we can point to the deepest node.
        field_name = str(node.chain[-1])
        loop_type = type
        chain_to_parse = node.chain[1:]
        previous_types = []
        resolved_chain: list[str] = [str(node.chain[0])]
        while True:
            if isinstance(loop_type, FieldTraverserType):
                chain_to_parse = loop_type.chain + chain_to_parse
                loop_type = loop_type.table_type
                continue
            previous_types.append(loop_type)
            if len(chain_to_parse) == 0:
                break
            next_chain = chain_to_parse.pop(0)
            if next_chain == "..":  # only support one level of ".."
                previous_types.pop()
                previous_types.pop()
                loop_type = previous_types[-1]
                next_chain = chain_to_parse.pop(0)

            try:
                loop_type = loop_type.get_child(str(next_chain), self.context)
            except NotImplementedError:
                raise QueryError(
                    f"Cannot access property '{next_chain}' on '{'.'.join(resolved_chain)}'. "
                    f"This can happen when a column alias shadows a table field. Try renaming the alias."
                )
            resolved_chain.append(str(next_chain))
            # Note: get_child currently always raises rather than returning None,
            # but this guard is kept for safety in case that contract changes.
            if loop_type is None:
                raise ResolutionError(f"Cannot resolve type {'.'.join(node.chain)}. Unable to resolve {next_chain}.")
        node.type = loop_type

        if isinstance(node.type, ast.ExpressionFieldType):
            # only swap out expression fields in ClickHouse
            if self.dialect == "clickhouse":
                new_expr = clone_expr(node.type.expr)
                new_node: ast.Expr = ast.Alias(alias=node.type.name, expr=new_expr, hidden=True)

                if node.type.isolate_scope:
                    table_type = node.type.table_type
                    while isinstance(table_type, ast.VirtualTableType):
                        table_type = table_type.table_type
                    self.scopes.append(ast.SelectQueryType(tables={node.type.name: table_type}))

                new_node = self.visit(new_node)

                if node.type.isolate_scope:
                    self.scopes.pop()
                return new_node

        if isinstance(node.type, ast.FieldType) and node.start is not None and node.end is not None:
            self.context.add_notice(
                start=node.start,
                end=node.end,
                message=f"Field '{node.type.name}' is of type '{node.type.resolve_constant_type(self.context).print_type()}'",
            )

        if isinstance(node.type, ast.FieldType):
            return ast.Alias(
                alias=field_name or node.type.name,
                expr=node,
                hidden=True,
                type=ast.FieldAliasType(alias=node.type.name, type=node.type),
            )
        elif isinstance(node.type, ast.PropertyType):
            property_alias = "__".join(str(s) for s in node.type.chain)
            return ast.Alias(
                alias=property_alias,
                expr=node,
                hidden=True,
                type=ast.FieldAliasType(alias=property_alias, type=node.type),
            )

        return node

    def visit_array_access(self, node: ast.ArrayAccess):
        node = super().visit_array_access(node)

        if self.dialect == "clickhouse" and isinstance(node.property, ast.Constant) and node.property.value == 0:
            raise QueryError("SQL indexes start from one, not from zero. E.g: array[1]")

        array = node.array
        while isinstance(array, ast.Alias):
            array = array.expr

        if (
            isinstance(array, ast.Field)
            and isinstance(node.property, ast.Constant)
            and (isinstance(node.property.value, str) or isinstance(node.property.value, int))
            and (
                (isinstance(array.type, ast.PropertyType))
                or (
                    isinstance(array.type, ast.FieldType)
                    and isinstance(
                        array.type.resolve_database_field(self.context),
                        StringJSONDatabaseField,
                    )
                )
            )
        ):
            array.chain.append(node.property.value)
            array.type = array.type.get_child(node.property.value, self.context)
            return array

        return node

    def visit_tuple_access(self, node: ast.TupleAccess):
        node = super().visit_tuple_access(node)

        if self.dialect == "clickhouse" and node.index == 0:
            raise QueryError("SQL indexes start from one, not from zero. E.g: array.1")

        tuple = node.tuple
        while isinstance(tuple, ast.Alias):
            tuple = tuple.expr

        if isinstance(tuple, ast.Field) and (
            (isinstance(tuple.type, ast.PropertyType))
            or (
                isinstance(tuple.type, ast.FieldType)
                and isinstance(tuple.type.resolve_database_field(self.context), StringJSONDatabaseField)
            )
        ):
            tuple.chain.append(node.index)
            tuple.type = tuple.type.get_child(node.index, self.context)
            return tuple

        return node

    def visit_dict(self, node: ast.Dict):
        return self.visit(convert_to_hx(node))

    def visit_between_expr(self, node: ast.BetweenExpr):
        node = super().visit_between_expr(node)
        node.type = ast.BooleanType(nullable=False)
        return node

    def visit_is_distinct_from(self, node: ast.IsDistinctFrom):
        node = super().visit_is_distinct_from(node)
        node.type = ast.BooleanType(nullable=False)
        return node

    def visit_constant(self, node: ast.Constant):
        node = super().visit_constant(node)
        node.type = resolve_constant_data_type(node.value)
        return node

    def visit_and(self, node: ast.And):
        node = super().visit_and(node)
        node.type = ast.BooleanType(
            nullable=any(
                (expr.type or ast.UnknownType()).resolve_constant_type(self.context).nullable for expr in node.exprs
            )
        )
        return node

    def visit_or(self, node: ast.Or):
        node = super().visit_or(node)
        node.type = ast.BooleanType(
            nullable=any(
                (expr.type or ast.UnknownType()).resolve_constant_type(self.context).nullable for expr in node.exprs
            )
        )
        return node

    def visit_not(self, node: ast.Not):
        node = super().visit_not(node)
        node.type = ast.BooleanType(
            nullable=(node.expr.type or ast.UnknownType()).resolve_constant_type(self.context).nullable
        )
        return node

    def visit_compare_operation(self, node: ast.CompareOperation):
        if self.context.modifiers.inCohortVia == "subquery":
            if node.op == ast.CompareOperationOp.InCohort:
                return self.visit(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.In,
                        left=node.left,
                        right=cohort_query_node(node.right, context=self.context),
                    )
                )
            elif node.op == ast.CompareOperationOp.NotInCohort:
                return self.visit(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.NotIn,
                        left=node.left,
                        right=cohort_query_node(node.right, context=self.context),
                    )
                )

        node = super().visit_compare_operation(node)
        node.type = ast.BooleanType(nullable=False)

        if (
            USE_GLOBAL_JOINS
            and (node.op == ast.CompareOperationOp.In or node.op == ast.CompareOperationOp.NotIn)
            and self._is_events_table(node.left)
            and self._is_s3_cluster(node.right)
        ):
            if node.op == ast.CompareOperationOp.In:
                node.op = ast.CompareOperationOp.GlobalIn
            else:
                node.op = ast.CompareOperationOp.GlobalNotIn

        if (
            (node.op == ast.CompareOperationOp.In or node.op == ast.CompareOperationOp.NotIn)
            and isinstance(node.right, ast.SelectQuery)
            and (self._is_sessions_table(node.left) or self._select_reads_sessions(node.right))
        ):
            if node.op == ast.CompareOperationOp.In:
                node.op = ast.CompareOperationOp.GlobalIn
            else:
                node.op = ast.CompareOperationOp.GlobalNotIn

        return node

    def _get_scope(self):
        if len(self.scopes) > 0:
            return self.scopes[-1]
        elif len(self.ctes) > 0:
            # Use an empty scope to allow lookups on any present CTEs
            return EMPTY_SCOPE
        else:
            raise QueryError("No scope or CTE available")

    # Used to find events table in current scope for action functions
    def _get_events_table_current_scope(self) -> tuple[Optional[str], Optional[EventsTable]]:
        scope = self._get_scope()
        for alias, table_type in scope.tables.items():
            if isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable):
                return alias, table_type.table

            if isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
                if isinstance(table_type.table_type, ast.TableType) and isinstance(
                    table_type.table_type.table, EventsTable
                ):
                    return alias, table_type.table_type.table

        return None, None

    def _is_events_table(self, node: ast.Expr) -> bool:
        while isinstance(node, ast.Alias):
            node = node.expr
        if isinstance(node, ast.Field) and isinstance(node.type, ast.FieldType):
            if isinstance(node.type.table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
                return isinstance(node.type.table_type.table_type.table, EventsTable)
            if isinstance(node.type.table_type, ast.TableType):
                return isinstance(node.type.table_type.table, EventsTable)
        elif isinstance(node, ast.Field) and isinstance(node.type, ast.PropertyType):
            if isinstance(node.type.field_type.table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
                return isinstance(node.type.field_type.table_type.table_type.table, EventsTable)
            if isinstance(node.type.field_type.table_type, ast.TableType):
                return isinstance(node.type.field_type.table_type.table, EventsTable)
        return False

    # The set of "sessions-cluster" tables is whatever the current database resolves
    # for these names — adding a new sessions version means wiring it up in
    # database.py, and this helper picks it up automatically.
    _SESSIONS_TABLE_NAMES = ("sessions", "raw_sessions", "raw_sessions_v3")

    def _sessions_table_classes(self) -> tuple[type, ...]:
        database = self.context.database
        if database is None:
            return ()
        return tuple(
            {type(database.get_table(name)) for name in self._SESSIONS_TABLE_NAMES if database.has_table(name)}
        )

    def _is_sessions_table(self, node: ast.Expr) -> bool:
        classes = self._sessions_table_classes()
        if not classes:
            return False
        while isinstance(node, ast.Alias):
            node = node.expr
        if not isinstance(node, ast.Field):
            return False
        field_type = node.type
        if isinstance(field_type, ast.PropertyType):
            field_type = field_type.field_type
        if not isinstance(field_type, ast.FieldType):
            return False
        table_type = field_type.table_type
        while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
            table_type = table_type.table_type
        if isinstance(table_type, (ast.LazyTableType, ast.TableType)):
            return isinstance(table_type.table, classes)
        if isinstance(table_type, ast.LazyJoinType):
            return isinstance(table_type.lazy_join.join_table, classes)
        return False

    def _select_reads_sessions(self, node: ast.SelectQuery) -> bool:
        classes = self._sessions_table_classes()
        if not classes:
            return False
        join = node.select_from
        while join is not None:
            if isinstance(join.table, ast.Field) and isinstance(join.table.type, ast.BaseTableType):
                table_type: ast.Type = join.table.type
                while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
                    table_type = table_type.table_type
                if isinstance(table_type, (ast.LazyTableType, ast.TableType)) and isinstance(table_type.table, classes):
                    return True
            join = join.next_join
        return False

    def _is_s3_cluster(self, node: ast.Expr) -> bool:
        while isinstance(node, ast.Alias):
            node = node.expr
        if (
            isinstance(node, ast.SelectQuery)
            and node.select_from
            and isinstance(node.select_from.type, ast.BaseTableType)
        ):
            if isinstance(node.select_from.type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
                return isinstance(node.select_from.type.table_type.table, S3Table)
            elif isinstance(node.select_from.type, ast.TableType):
                return isinstance(node.select_from.type.table, S3Table)
        return False

    def _is_s3_table(self, table: ast.TableOrSelectType) -> bool:
        if isinstance(table, (ast.TableAliasType, ast.ColumnAliasedTableType)):
            return self._is_s3_table(table.table_type)

        if isinstance(table, ast.CTETableAliasType):
            return self._is_s3_table(table.cte_table_type)

        if isinstance(table, ast.CTETableType):
            tables = self._extract_tables_from_query_type(table.select_query_type)
            return any(self._is_s3_table(inner_table) for inner_table in tables)

        if isinstance(table, ast.TableType):
            return isinstance(table.table, S3Table)

        return False

    def _is_next_s3(self, node: Optional[ast.JoinExpr]):
        if node is None:
            return False
        if isinstance(
            node.type,
            (ast.TableAliasType, ast.ColumnAliasedTableType, ast.CTETableAliasType, ast.CTETableType, ast.TableType),
        ):
            return self._is_s3_table(node.type)
        return False

    def _extract_tables_from_query_type(
        self, select_query_type: ast.SelectQueryType | ast.SelectSetQueryType
    ) -> list[ast.TableOrSelectType]:
        tables: list[ast.TableOrSelectType] = []
        if isinstance(select_query_type, ast.SelectQueryType):
            for t in select_query_type.tables.values():
                if isinstance(t, ast.SelectQueryAliasType):
                    tables.extend(self._extract_tables_from_query_type(t.select_query_type))
                else:
                    tables.append(t)

            for at in select_query_type.anonymous_tables:
                tables.extend(self._extract_tables_from_query_type(at))
        else:
            for sqt in select_query_type.types:
                tables.extend(self._extract_tables_from_query_type(sqt))

        return tables
