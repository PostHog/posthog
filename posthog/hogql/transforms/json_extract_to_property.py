"""Early ClickHouse pass: normalize a literal `JSONExtractString(properties, 'x')` into a property-access read.

Users sometimes write `JSONExtractString(properties, '$browser')` (or a typed `JSONExtract(properties, 'x', 'T')`)
directly instead of `properties.$browser`. When the property is backed by a materialized column, decompressing the
whole JSON blob is wasted I/O. This pass rewrites such a call into the same property-access `Field` that
`properties.$browser` produces, so the rest of the pipeline (lazy-table resolution, lowering, ClickHouse property
resolution) treats the two forms identically and routes both to the materialized column.

It runs *before* `resolve_lazy_tables`, so the produced read flows through the lazy-table machinery the same way a chain
access does — that is what lets a read off the lazy `persons`/`groups` tables reach its materialized column inside the
generated subquery, rather than being stranded as a raw JSON extract.

Behavior-preserving: it only rewrites when a static materialized column already exists and its physical type matches the
requested JSON type. A call with no materialized column is left untouched and prints as the raw JSON extract, so its
ClickHouse semantics (e.g. `''` for a missing key) are unchanged. The choice of which physical column to read, and the
access-control NULLing of restricted properties, are left entirely to the downstream resolution pass.
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

        # Unwrap Alias if present (the resolver wraps fields in Alias nodes).
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

        # resolve_database_table is polymorphic across concrete, lazy, alias, and virtual table types, so one call
        # resolves the ClickHouse table name for a read off `events`, `raw_persons`, the lazy `persons`/`groups` tables,
        # or the person-on-events virtual table alike. The materialized-column registry is keyed by that ClickHouse name
        # (RawPersonsTable is "raw_persons" in HogQL but "person" in ClickHouse), which is why we don't use the HogQL name.
        table_type = field_type.table_type
        if not isinstance(table_type, ast.BaseTableType):
            return None
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
        # JSONExtractString has string semantics, so it only matches a string-backed column.
        # A non-string materialized column (e.g. Nullable(Float64)) would otherwise be rewritten
        # to the bare typed column, dropping the string type the surrounding query expects.
        return parse_sql_runtime_type(mat_col.type).family == "string"

    if node.name != "JSONExtract" or len(node.args) != 3:
        return False

    type_arg = node.args[2]
    if not isinstance(type_arg, ast.Constant) or not isinstance(type_arg.value, str):
        return False

    # Normalize before comparing so formatting differences in the type spelling
    # (whitespace, quoting) don't block the rewrite; semantic differences
    # (nullability, width, timezone) still do, because JSON helper semantics for
    # missing keys and out-of-range values differ from bare column semantics.
    requested_type = normalized_runtime_type(parse_sql_runtime_type(type_arg.value))
    materialized_type = normalized_runtime_type(parse_sql_runtime_type(mat_col.type))
    return requested_type.family != "unknown" and requested_type == materialized_type
