"""Normalize a literal `JSONExtractString(properties, 'x')` into a `properties.x` property-access read.

Runs before `resolve_lazy_tables` so the rewritten read flows through the same pipeline as chain access and reaches its
materialized column, including inside the lazy persons/groups subquery — which the old in-place rewrite, running after
lazy resolution, could not.

Only rewrites when a static materialized column exists and its type matches; an unbacked call stays a raw JSON extract.
Column choice and restricted-property NULLing are left to the downstream resolution pass.
"""

from typing import cast

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import StringJSONDatabaseField
from posthog.hogql.type_system import normalized_runtime_type, parse_sql_runtime_type
from posthog.hogql.visitor import CloningVisitor

from posthog.clickhouse.materialized_columns import (
    MATERIALIZATION_VALID_TABLES,
    MaterializedColumn,
    TablesWithMaterializedColumns,
    get_materialized_column_for_property,
)
from posthog.models.property import TableColumn


def normalize_json_extract_to_property(node: _T_AST, context: HogQLContext) -> _T_AST:
    return cast(_T_AST, JSONExtractToPropertyNormalizer(context).visit(node))


class JSONExtractToPropertyNormalizer(CloningVisitor):
    def __init__(self, context: HogQLContext) -> None:
        # The AST is still type-resolved at this point and downstream passes rely on those types.
        super().__init__(clear_types=False)
        self.context = context

    def visit_call(self, node: ast.Call) -> ast.Expr:
        rewritten = self._try_normalize(node)
        if rewritten is not None:
            return rewritten
        return super().visit_call(node)

    def _try_normalize(self, node: ast.Call) -> ast.Field | None:
        property_name = _simple_json_extract_property_name(node)
        if property_name is None:
            return None

        field_arg = node.args[0]
        if isinstance(field_arg, ast.Alias):
            field_arg = field_arg.expr
        if not isinstance(field_arg, ast.Field):
            return None

        field_type = field_arg.type
        if isinstance(field_type, ast.FieldAliasType):
            field_type = field_type.type
        if not isinstance(field_type, ast.FieldType):
            return None

        database_field = field_type.resolve_database_field(self.context)
        if not isinstance(database_field, StringJSONDatabaseField):
            return None

        table_type = field_type.table_type
        if not isinstance(table_type, ast.BaseTableType):
            return None
        # Registry is keyed by the ClickHouse name, not the HogQL name (raw_persons -> person); resolve_database_table covers lazy and virtual tables too.
        table_name = table_type.resolve_database_table(self.context).to_printed_clickhouse(self.context)
        if table_name not in MATERIALIZATION_VALID_TABLES:
            return None

        field_name = cast(TableColumn, database_field.name)
        mat_col = get_materialized_column_for_property(
            cast(TablesWithMaterializedColumns, table_name),
            field_name,
            property_name,
        )
        if mat_col is None:
            return None

        if not _json_extract_matches_materialized_column_type(node, mat_col):
            return None

        return ast.Field(
            start=node.start,
            end=node.end,
            chain=[*field_arg.chain, property_name],
            type=ast.PropertyType(chain=[property_name], field_type=field_type),
        )


def _simple_json_extract_property_name(node: ast.Call) -> str | None:
    if node.name == "JSONExtractString" and len(node.args) == 2:
        prop_name_arg = node.args[1]
    elif node.name == "JSONExtract" and len(node.args) == 3:
        prop_name_arg = node.args[1]
    else:
        return None

    if isinstance(prop_name_arg, ast.Constant) and isinstance(prop_name_arg.value, str):
        return prop_name_arg.value
    return None


def _json_extract_matches_materialized_column_type(node: ast.Call, mat_col: MaterializedColumn) -> bool:
    if node.name == "JSONExtractString":
        # JSONExtractString is string-typed, so only a string-backed column is an equivalent rewrite.
        return parse_sql_runtime_type(mat_col.type).family == "string"

    if node.name != "JSONExtract" or len(node.args) != 3:
        return False

    type_arg = node.args[2]
    if not isinstance(type_arg, ast.Constant) or not isinstance(type_arg.value, str):
        return False

    # Normalize spellings so formatting differences don't block the rewrite, while real type differences (nullability, width, tz) still do.
    requested_type = normalized_runtime_type(parse_sql_runtime_type(type_arg.value))
    materialized_type = normalized_runtime_type(parse_sql_runtime_type(mat_col.type))
    return requested_type.family != "unknown" and requested_type == materialized_type
