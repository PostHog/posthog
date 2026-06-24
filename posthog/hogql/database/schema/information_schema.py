"""HogQL `information_schema`: a self-describing, queryable view of the database catalog.

Nested under the `system` namespace, these virtual tables let agents (and humans) discover what
tables, columns, data types, relationships, and descriptions are available without leaving HogQL:

    SELECT * FROM system.information_schema.columns WHERE table_name = 'events'
    SELECT * FROM system.information_schema.relationships WHERE source_table = 'events'

The rows are computed at query time from the live, per-team `Database` object, so they always
reflect the caller's own access (denied/hidden tables never appear). Descriptions are read
uniformly from `FieldOrTable.description`; for data warehouse tables they are merged in from the
`WarehouseColumnAnnotation` semantic layer, fetched lazily only when these tables are queried.
"""

from typing import TYPE_CHECKING, Any, Optional

import structlog

from posthog.hogql import ast
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    DecimalDatabaseField,
    ExpressionField,
    FieldOrTable,
    FieldTraverser,
    FloatArrayDatabaseField,
    FloatDatabaseField,
    IntegerDatabaseField,
    LazyJoin,
    LazyTable,
    LazyTableToAdd,
    SavedQuery,
    StringArrayDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    StructDatabaseField,
    Table,
    TableNode,
    UnknownDatabaseField,
    UUIDDatabaseField,
    VirtualTable,
)

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.database.database import Database

logger = structlog.get_logger(__name__)


# --- value coercion --------------------------------------------------------------------------- #
# Every cell in the constant-row array is emitted as a String so ClickHouse infers a single,
# unambiguous `Array(Tuple(String, ...))` type (no NULL-vs-typed inference surprises). The outer
# SELECT then casts each column back to its declared type. `""` is the wire form of SQL NULL for
# nullable columns and is converted back with `nullIf` / `*OrNull`.
_STRING = "string"
_NULLABLE_STRING = "nullable_string"
_INTEGER = "integer"
_NULLABLE_INTEGER = "nullable_integer"
_BOOLEAN = "boolean"


def _cell(value: Any) -> ast.Constant:
    """Render a single row value as a String constant for the inner array."""
    if value is None:
        return ast.Constant(value="")
    if isinstance(value, bool):
        return ast.Constant(value="true" if value else "false")
    return ast.Constant(value=str(value))


def _column_expr(kind: str, index: int) -> ast.Expr:
    """Cast `row.<index>` (always a String) back to the column's declared type."""
    source = ast.TupleAccess(tuple=ast.Field(chain=["row"]), index=index)
    if kind == _STRING:
        return source
    if kind == _NULLABLE_STRING:
        return ast.Call(name="nullIf", args=[source, ast.Constant(value="")])
    if kind == _INTEGER:
        return ast.Call(name="toIntOrZero", args=[source])
    if kind == _NULLABLE_INTEGER:
        return ast.Call(name="accurateCastOrNull", args=[source, ast.Constant(value="Int64")])
    if kind == _BOOLEAN:
        return ast.Call(name="equals", args=[source, ast.Constant(value="true")])
    raise ValueError(f"Unknown information_schema column kind: {kind}")


def _constant_rows_select(columns: list[tuple[str, str]], rows: list[list[Any]]) -> ast.SelectQuery:
    """Build `SELECT <casts> FROM (SELECT arrayJoin([(...), ...]) AS row)` for the given rows.

    `columns` is a list of `(column_name, kind)`. Each row is a list of python values aligned to
    `columns`. An empty `rows` yields the correct columns with zero rows via `LIMIT 0`.
    """
    limit_zero = not rows
    if limit_zero:
        rows = [["" for _ in columns]]

    array = ast.Array(exprs=[ast.Tuple(exprs=[_cell(v) for v in row]) for row in rows])
    inner = ast.SelectQuery(select=[ast.Alias(alias="row", expr=ast.Call(name="arrayJoin", args=[array]))])

    select = ast.SelectQuery(
        select=[
            ast.Alias(alias=name, expr=_column_expr(kind, index + 1)) for index, (name, kind) in enumerate(columns)
        ],
        select_from=ast.JoinExpr(table=inner),
    )
    if limit_zero:
        select.limit = ast.Constant(value=0)
    return select


# --- schema introspection --------------------------------------------------------------------- #

_FIELD_TYPE_NAMES: list[tuple[type, str]] = [
    # Order matters: more specific subclasses first.
    (IntegerDatabaseField, "Integer"),
    (FloatDatabaseField, "Float"),
    (DecimalDatabaseField, "Decimal"),
    (BooleanDatabaseField, "Boolean"),
    (UUIDDatabaseField, "UUID"),
    (DateTimeDatabaseField, "DateTime"),
    (DateDatabaseField, "Date"),
    (StringJSONDatabaseField, "JSON"),
    (StructDatabaseField, "Struct"),
    (StringArrayDatabaseField, "Array"),
    (FloatArrayDatabaseField, "Array"),
    (StringDatabaseField, "String"),
    (UnknownDatabaseField, "Unknown"),
]


def _field_type_name(field: DatabaseField) -> str:
    if isinstance(field, ExpressionField):
        return "Expression"
    for cls, name in _FIELD_TYPE_NAMES:
        if isinstance(field, cls):
            return name
    return "Unknown"


def _classify_table(name: str, table: Table, warehouse: set[str], views: set[str]) -> tuple[str, str]:
    """Return `(table_type, table_schema)` for a table by its fully-qualified name."""
    if name.startswith("system.information_schema."):
        return "information_schema", "information_schema"
    if name.startswith("system."):
        return "system", "system"
    if name in warehouse:
        return "data_warehouse", "warehouse"
    if name in views or isinstance(table, SavedQuery):
        return "view", "views"
    return "posthog", "public"


def _visible_table_names(database: "Database") -> list[str]:
    # `posthog.*` is an internal namespace that mostly duplicates the top-level tables — skip it
    # to keep the catalog clean. Everything else (built-in, system, warehouse, views) is included.
    return [n for n in database.tables.resolve_visible_table_names() if not n.startswith("posthog.")]


def _warehouse_metadata(team_id: Optional[int]) -> tuple[dict[tuple[str, str], str], dict[str, Optional[int]]]:
    """Lazily load warehouse semantic descriptions and row counts for the team.

    Returns `(descriptions, row_counts)` where descriptions is keyed by `(table_name, column_name)`
    with `""` denoting the table-level description. Only runs when an information_schema table is
    actually queried, so it never touches the hot `create_hogql_database` path.
    """
    descriptions: dict[tuple[str, str], str] = {}
    row_counts: dict[str, Optional[int]] = {}
    if team_id is None:
        return descriptions, row_counts

    # Inline imports: keeps the products dependency off the hogql import path (avoids an import
    # cycle, since products import hogql) and off every non-information_schema query.
    from posthog.models.scoping import team_scope  # noqa: PLC0415

    from products.warehouse_sources.backend.models.column_annotation import WarehouseColumnAnnotation  # noqa: PLC0415
    from products.warehouse_sources.backend.models.table import DataWarehouseTable  # noqa: PLC0415

    try:
        with team_scope(team_id):
            for table_name, column_name, description in WarehouseColumnAnnotation.objects.values_list(
                "table__name", "column_name", "description"
            ):
                descriptions[(table_name, column_name)] = description
            for table_name, row_count in DataWarehouseTable.objects.values_list("name", "row_count"):
                row_counts[table_name] = row_count
    except Exception:
        # Schema discovery must never fail a query because the warehouse metadata could not be read,
        # but log so a transient DB error can be told apart from a real bug in the fetch loop.
        logger.exception("information_schema: failed to load warehouse metadata", team_id=team_id)
        return {}, {}

    return descriptions, row_counts


class _Introspection:
    """Walks the live database once and produces the rows for every information_schema table."""

    def __init__(self, database: "Database", context: "HogQLContext") -> None:
        self.database = database
        self.warehouse = set(database.get_warehouse_table_names())
        self.views = set(database.get_view_names())
        self.descriptions, self.row_counts = _warehouse_metadata(context.team_id)

    def _table_description(self, table: Table, table_type: str) -> Optional[str]:
        if table.description:
            return table.description
        if table_type == "data_warehouse" and table.name:
            return self.descriptions.get((table.name, ""))
        return None

    def _column_description(
        self, table: Table, table_type: str, column_name: str, field: FieldOrTable
    ) -> Optional[str]:
        if field.description:
            return field.description
        if table_type == "data_warehouse" and table.name:
            return self.descriptions.get((table.name, column_name))
        return None

    def collect(self) -> tuple[list[list[Any]], list[list[Any]], list[list[Any]]]:
        table_rows: list[list[Any]] = []
        column_rows: list[list[Any]] = []
        relationship_rows: list[list[Any]] = []

        for name in _visible_table_names(self.database):
            try:
                table = self.database.get_table(name)
            except Exception:
                # Denied or unresolvable for this caller — leave it out of the catalog entirely.
                continue

            table_type, table_schema = _classify_table(name, table, self.warehouse, self.views)
            row_count = self.row_counts.get(table.name) if table_type == "data_warehouse" and table.name else None
            table_rows.append(
                [name, table_schema, name, table_type, self._table_description(table, table_type), row_count]
            )

            self._collect_fields(name, table_schema, table_type, table, table.fields, column_rows, relationship_rows)

        return table_rows, column_rows, relationship_rows

    def _collect_fields(
        self,
        table_name: str,
        table_schema: str,
        table_type: str,
        table: Table,
        fields: dict[str, FieldOrTable],
        column_rows: list[list[Any]],
        relationship_rows: list[list[Any]],
        *,
        prefix: str = "",
        ordinal_start: int = 1,
    ) -> int:
        """Append column/relationship rows for `fields` and return the next free ordinal_position."""
        ordinal = ordinal_start
        for field_name, field in fields.items():
            if field.hidden:
                continue
            qualified = f"{prefix}{field_name}"

            if isinstance(field, DatabaseField):
                kind = "expression" if isinstance(field, ExpressionField) else "column"
                column_rows.append(
                    [
                        table_schema,
                        table_name,
                        qualified,
                        ordinal,
                        _field_type_name(field),
                        bool(field.is_nullable()),
                        bool(field.array),
                        kind,
                        self._column_description(table, table_type, qualified, field),
                    ]
                )
                ordinal += 1
            elif isinstance(field, LazyJoin):
                target = field.join_table if isinstance(field.join_table, str) else (field.join_table.name or "")
                relationship_rows.append(
                    [
                        table_name,
                        ".".join(str(x) for x in field.from_field),
                        target,
                        ".".join(str(x) for x in field.to_field) if field.to_field else None,
                        "lazy_join",
                        field.resolver,
                    ]
                )
            elif isinstance(field, FieldTraverser):
                relationship_rows.append(
                    [
                        table_name,
                        qualified,
                        table_name,
                        ".".join(str(x) for x in field.chain),
                        "field_traverser",
                        None,
                    ]
                )
            elif isinstance(field, VirtualTable):
                # Surface nested virtual-table columns as `parent.child` columns.
                column_rows.append(
                    [table_schema, table_name, qualified, ordinal, "VirtualTable", False, False, "virtual_table", None]
                )
                ordinal += 1
                ordinal = self._collect_fields(
                    table_name,
                    table_schema,
                    table_type,
                    table,
                    field.fields,
                    column_rows,
                    relationship_rows,
                    prefix=f"{qualified}.",
                    ordinal_start=ordinal,
                )

        return ordinal


def _introspect(context: "HogQLContext") -> tuple[list[list[Any]], list[list[Any]], list[list[Any]]]:
    """Introspect the database once per query, reusing the result across information_schema tables.

    A query that joins several information_schema tables would otherwise rebuild the full
    introspection — including the warehouse-metadata ORM queries — once per referenced table.
    """
    if context.information_schema_introspection is None:
        database = context.database
        if database is None:
            return [], [], []
        context.information_schema_introspection = _Introspection(database, context).collect()
    return context.information_schema_introspection


# --- the virtual tables ----------------------------------------------------------------------- #

_TABLES_COLUMNS: list[tuple[str, str]] = [
    ("table_catalog", _STRING),
    ("table_schema", _STRING),
    ("table_name", _STRING),
    ("table_type", _STRING),
    ("description", _NULLABLE_STRING),
    ("row_count", _NULLABLE_INTEGER),
]

_COLUMNS_COLUMNS: list[tuple[str, str]] = [
    ("table_schema", _STRING),
    ("table_name", _STRING),
    ("column_name", _STRING),
    ("ordinal_position", _INTEGER),
    ("data_type", _STRING),
    ("is_nullable", _BOOLEAN),
    ("is_array", _BOOLEAN),
    ("field_kind", _STRING),
    ("description", _NULLABLE_STRING),
]

_RELATIONSHIPS_COLUMNS: list[tuple[str, str]] = [
    ("source_table", _STRING),
    ("source_column", _STRING),
    ("target_table", _STRING),
    ("target_column", _NULLABLE_STRING),
    ("relationship_kind", _STRING),
    ("via", _NULLABLE_STRING),
]

_DATA_TYPES: list[tuple[str, str]] = [
    ("String", "Text / string values."),
    ("Integer", "Whole numbers."),
    ("Float", "Floating-point numbers."),
    ("Decimal", "Fixed-precision decimal numbers."),
    ("Boolean", "True / false values."),
    ("Date", "Calendar date (no time component)."),
    ("DateTime", "Timestamp with date and time."),
    ("UUID", "Universally unique identifier (rendered as a string)."),
    ("JSON", "JSON document; access nested keys with `field.key` or `field.key.subkey`."),
    ("Array", "Ordered list of values."),
    ("Struct", "Nested record with named sub-fields."),
    ("Expression", "Computed column derived from other columns at query time."),
    ("VirtualTable", "Nested group of columns sharing the parent table's storage."),
    ("Unknown", "Type could not be determined."),
]


def _string_field(name: str, nullable: bool = False) -> StringDatabaseField:
    return StringDatabaseField(name=name, nullable=nullable)


class InformationSchemaTablesTable(LazyTable):
    fields: dict[str, FieldOrTable] = {
        "table_catalog": _string_field("table_catalog", nullable=False),
        "table_schema": _string_field("table_schema", nullable=False),
        "table_name": _string_field("table_name", nullable=False),
        "table_type": _string_field("table_type", nullable=False),
        "description": _string_field("description", nullable=True),
        "row_count": IntegerDatabaseField(name="row_count", nullable=True),
    }

    def lazy_select(self, table_to_add: LazyTableToAdd, context: "HogQLContext", node: Any) -> ast.SelectQuery:
        table_rows, _, _ = _introspect(context)
        return _constant_rows_select(_TABLES_COLUMNS, table_rows)

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return "information_schema.tables"

    def to_printed_hogql(self) -> str:
        return "system__information_schema__tables"


class InformationSchemaColumnsTable(LazyTable):
    fields: dict[str, FieldOrTable] = {
        "table_schema": _string_field("table_schema", nullable=False),
        "table_name": _string_field("table_name", nullable=False),
        "column_name": _string_field("column_name", nullable=False),
        "ordinal_position": IntegerDatabaseField(name="ordinal_position", nullable=False),
        "data_type": _string_field("data_type", nullable=False),
        "is_nullable": BooleanDatabaseField(name="is_nullable", nullable=False),
        "is_array": BooleanDatabaseField(name="is_array", nullable=False),
        "field_kind": _string_field("field_kind", nullable=False),
        "description": _string_field("description", nullable=True),
    }

    def lazy_select(self, table_to_add: LazyTableToAdd, context: "HogQLContext", node: Any) -> ast.SelectQuery:
        _, column_rows, _ = _introspect(context)
        return _constant_rows_select(_COLUMNS_COLUMNS, column_rows)

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return "information_schema.columns"

    def to_printed_hogql(self) -> str:
        return "system__information_schema__columns"


class InformationSchemaRelationshipsTable(LazyTable):
    fields: dict[str, FieldOrTable] = {
        "source_table": _string_field("source_table", nullable=False),
        "source_column": _string_field("source_column", nullable=False),
        "target_table": _string_field("target_table", nullable=False),
        "target_column": _string_field("target_column", nullable=True),
        "relationship_kind": _string_field("relationship_kind", nullable=False),
        "via": _string_field("via", nullable=True),
    }

    def lazy_select(self, table_to_add: LazyTableToAdd, context: "HogQLContext", node: Any) -> ast.SelectQuery:
        _, _, relationship_rows = _introspect(context)
        return _constant_rows_select(_RELATIONSHIPS_COLUMNS, relationship_rows)

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return "information_schema.relationships"

    def to_printed_hogql(self) -> str:
        return "system__information_schema__relationships"


class InformationSchemaDataTypesTable(LazyTable):
    fields: dict[str, FieldOrTable] = {
        "type_name": _string_field("type_name", nullable=False),
        "description": _string_field("description", nullable=False),
    }

    def lazy_select(self, table_to_add: LazyTableToAdd, context: "HogQLContext", node: Any) -> ast.SelectQuery:
        return _constant_rows_select(
            [("type_name", _STRING), ("description", _STRING)],
            [[type_name, description] for type_name, description in _DATA_TYPES],
        )

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return "information_schema.data_types"

    def to_printed_hogql(self) -> str:
        return "system__information_schema__data_types"


def information_schema_node() -> TableNode:
    """The `information_schema` namespace, mounted under `system` (see `SystemTables.children`)."""
    return TableNode(
        name="information_schema",
        children={
            "tables": TableNode(name="tables", table=InformationSchemaTablesTable()),
            "columns": TableNode(name="columns", table=InformationSchemaColumnsTable()),
            "relationships": TableNode(name="relationships", table=InformationSchemaRelationshipsTable()),
            "data_types": TableNode(name="data_types", table=InformationSchemaDataTypesTable()),
        },
    )
