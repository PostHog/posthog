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

import hashlib
from typing import TYPE_CHECKING, Any, Optional

import structlog

from posthog.hogql import ast
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DANGEROUS_NoTeamIdCheckTable,
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


def _warehouse_metadata(
    team_id: Optional[int],
) -> tuple[dict[tuple[str, str], str], dict[str, Optional[int]], dict[str, Optional[int]]]:
    """Lazily load warehouse semantic descriptions and row counts for the team.

    Returns `(descriptions, row_counts, view_row_counts)`. Descriptions are keyed by
    `(table_name, column_name)` with `""` denoting the table-level description. `row_counts` is keyed
    by warehouse table name, `view_row_counts` by saved-query (view) name. Only runs when an
    information_schema table is actually queried, so it never touches the hot
    `create_hogql_database` path. Mirrors how `serialize_database` sources counts so the catalog and
    the SQL-editor schema agree.
    """
    descriptions: dict[tuple[str, str], str] = {}
    row_counts: dict[str, Optional[int]] = {}
    view_row_counts: dict[str, Optional[int]] = {}
    if team_id is None:
        return descriptions, row_counts, view_row_counts

    # Inline imports: keeps the products dependency off the hogql import path (avoids an import
    # cycle, since products import hogql) and off every non-information_schema query.
    from posthog.models.scoping import team_scope  # noqa: PLC0415

    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery  # noqa: PLC0415
    from products.warehouse_sources.backend.models.column_annotation import WarehouseColumnAnnotation  # noqa: PLC0415
    from products.warehouse_sources.backend.models.table import DataWarehouseTable  # noqa: PLC0415

    try:
        with team_scope(team_id):
            for table_name, column_name, description in WarehouseColumnAnnotation.objects.values_list(
                "table__name", "column_name", "description"
            ):
                descriptions[(table_name, column_name)] = description
            # `.queryable()` (not `.objects`) drops soft-deleted tables and orphans of a soft-deleted
            # source — otherwise a re-synced table's dead duplicate clobbers the live row_count with a
            # stale/null value. Oldest first so the newest row wins a name collision, matching the
            # last-write-wins order `serialize_database` uses.
            for table_name, row_count in (
                DataWarehouseTable.objects.queryable().order_by("created_at").values_list("name", "row_count")
            ):
                row_counts[table_name] = row_count
            # Views carry their row count on the materialized backing table (`saved_query.table`).
            for view_name, row_count in (
                DataWarehouseSavedQuery.objects.exclude(deleted=True)
                .filter(team_id=team_id, table__isnull=False)
                .values_list("name", "table__row_count")
            ):
                view_row_counts[view_name] = row_count
    except Exception:
        # Schema discovery must never fail a query because the warehouse metadata could not be read,
        # but log so a transient DB error can be told apart from a real bug in the fetch loop.
        logger.exception("information_schema: failed to load warehouse metadata", team_id=team_id)
        return {}, {}, {}

    return descriptions, row_counts, view_row_counts


def _unwrap(expr: ast.Expr) -> ast.Expr:
    """Peel resolver-inserted `Alias` wrappers — a resolved WHERE turns `table_name` into
    `Alias(alias='table_name', expr=Field(...))`, so predicate matching has to see through them."""
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    return expr


def _constant_str(expr: ast.Expr) -> Optional[str]:
    """The string form of a non-null, non-bool constant expr, or None if it isn't one."""
    expr = _unwrap(expr)
    if isinstance(expr, ast.Constant) and expr.value is not None and not isinstance(expr.value, bool):
        return str(expr.value)
    return None


def _is_target_field(expr: ast.Expr, column: str) -> bool:
    expr = _unwrap(expr)
    return isinstance(expr, ast.Field) and bool(expr.chain) and expr.chain[-1] == column


def _bound_table_names(expr: Optional[ast.Expr], column: str) -> Optional[set[str]]:
    """Best-effort *superset* of the `column` values a WHERE expr can match.

    Returns None when no safe bound can be derived — the caller then emits every row and relies on
    ClickHouse to apply the real predicate. The invariant is one-directional: the returned set must
    never exclude a value the predicate could accept (that would drop valid rows), so anything not
    understood widens to None rather than guessing.
    """
    if expr is None:
        return None
    expr = _unwrap(expr)
    if isinstance(expr, ast.And):
        # An AND result satisfies every conjunct, so it lies within any bounded conjunct; intersect
        # the bounded ones for the tightest still-correct superset, ignoring conjuncts we can't bound.
        bound: Optional[set[str]] = None
        for child in expr.exprs:
            child_bound = _bound_table_names(child, column)
            if child_bound is None:
                continue
            bound = child_bound if bound is None else (bound & child_bound)
        return bound
    if isinstance(expr, ast.Or):
        # An OR result satisfies at least one branch, so every branch must be bounded to bound the
        # union — a single unbounded branch makes the whole disjunction unbounded.
        union: set[str] = set()
        for child in expr.exprs:
            child_bound = _bound_table_names(child, column)
            if child_bound is None:
                return None
            union |= child_bound
        return union
    if isinstance(expr, ast.CompareOperation):
        if expr.op == ast.CompareOperationOp.Eq:
            for field_side, value_side in ((expr.left, expr.right), (expr.right, expr.left)):
                if _is_target_field(field_side, column):
                    value = _constant_str(value_side)
                    return {value} if value is not None else None
            return None
        if expr.op in (ast.CompareOperationOp.In, ast.CompareOperationOp.GlobalIn):
            if _is_target_field(expr.left, column) and isinstance(expr.right, ast.Tuple | ast.Array):
                values = [_constant_str(e) for e in expr.right.exprs]
                return None if any(v is None for v in values) else {v for v in values if v is not None}
            return None
    return None


def _pushdown_table_filter(node: Any, column: str) -> Optional[frozenset[str]]:
    """Derive a table-name bound from a *simple* single-table information_schema query.

    Only attempted when the query selects from exactly one table with no joins: with a join a bare
    `table_name` reference is ambiguous between relations, and a wrong bound could silently drop rows,
    so we skip pushdown (return None → emit everything) rather than risk it.
    """
    if not isinstance(node, ast.SelectQuery) or node.select_from is None or node.select_from.next_join is not None:
        return None
    bound = _bound_table_names(node.where, column)
    return frozenset(bound) if bound is not None else None


# ClickHouse column types for the external data table, keyed by the same kinds as `_constant_rows_select`.
_KIND_TO_CLICKHOUSE: dict[str, str] = {
    _STRING: "String",
    _NULLABLE_STRING: "Nullable(String)",
    _INTEGER: "Int64",
    _NULLABLE_INTEGER: "Nullable(Int64)",
    # HogQL's BooleanDatabaseField maps to ClickHouse UInt8; Python bool serializes to it directly.
    _BOOLEAN: "UInt8",
}


def _column_field(name: str, kind: str) -> DatabaseField:
    if kind == _STRING:
        return StringDatabaseField(name=name, nullable=False)
    if kind == _NULLABLE_STRING:
        return StringDatabaseField(name=name, nullable=True)
    if kind == _INTEGER:
        return IntegerDatabaseField(name=name, nullable=False)
    if kind == _NULLABLE_INTEGER:
        return IntegerDatabaseField(name=name, nullable=True)
    if kind == _BOOLEAN:
        return BooleanDatabaseField(name=name, nullable=False)
    raise ValueError(f"Unknown information_schema column kind: {kind}")


class _ExternalDataTable(DANGEROUS_NoTeamIdCheckTable):
    """A query-scoped ClickHouse external data table, referenced by a bare name.

    Its rows travel out-of-band via `sync_execute(external_tables=...)`, so the printed query text
    stays small no matter how large the catalog is. `to_printed_clickhouse` emits the registered name
    verbatim; ClickHouse resolves it against the external data sent alongside the request. The
    no-team-id base is correct: the data is the caller's own catalog metadata, not cross-team rows.
    """

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return self.name or ""

    def to_printed_hogql(self) -> str:
        return self.name or ""


def _external_table_name(table_label: str, allowed: Optional[frozenset[str]]) -> str:
    # Deterministic per (table, pushdown filter) so re-registration within a query is idempotent and
    # the printed name always matches the data attached to the request.
    if allowed is None:
        suffix = "all"
    else:
        suffix = "f" + hashlib.md5("\x01".join(sorted(allowed)).encode()).hexdigest()[:12]
    return f"__ph_information_schema_{table_label}_{suffix}"


def _rows_select(
    context: "HogQLContext",
    table_label: str,
    columns: list[tuple[str, str]],
    rows: list[list[Any]],
    allowed: Optional[frozenset[str]],
) -> ast.SelectQuery:
    """Register `rows` as a query-scoped external data table and return a SELECT over it.

    Falls back to inlining the rows as constants when there's no live database to register against
    (in that case introspection returned no rows anyway).
    """
    database = context.database
    if database is None:
        return _constant_rows_select(columns, rows)

    column_names = [name for name, _ in columns]
    ext_name = _external_table_name(table_label, allowed)
    if ext_name not in context.external_tables:
        context.external_tables[ext_name] = {
            "name": ext_name,
            "structure": [(name, _KIND_TO_CLICKHOUSE[kind]) for name, kind in columns],
            "data": [dict(zip(column_names, row)) for row in rows],
        }
        fields: dict[str, FieldOrTable] = {name: _column_field(name, kind) for name, kind in columns}
        database.tables.add_child(
            TableNode(name=ext_name, table=_ExternalDataTable(name=ext_name, fields=fields), hidden=True),
            table_conflict_mode="override",
            children_conflict_mode="override",
        )

    return ast.SelectQuery(
        select=[ast.Alias(alias=name, expr=ast.Field(chain=[name])) for name in column_names],
        select_from=ast.JoinExpr(table=ast.Field(chain=[ext_name])),
    )


class _Introspection:
    """Walks the live database once and produces the rows for every information_schema table."""

    def __init__(
        self, database: "Database", context: "HogQLContext", allowed_tables: Optional[frozenset[str]] = None
    ) -> None:
        self.database = database
        self.allowed_tables = allowed_tables
        self.warehouse = set(database.get_warehouse_table_names())
        self.views = set(database.get_view_names())
        self.descriptions, self.row_counts, self.view_row_counts = _warehouse_metadata(context.team_id)

    def _row_count(self, name: str, table: Table, table_type: str) -> Optional[int]:
        if table_type == "data_warehouse" and table.name:
            return self.row_counts.get(table.name)
        if table_type == "view":
            # Views are keyed by their catalog name (the saved-query name), which is `name` here.
            return self.view_row_counts.get(name)
        return None

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

        names = _visible_table_names(self.database)
        if self.allowed_tables is not None:
            names = [name for name in names if name in self.allowed_tables]

        for name in names:
            try:
                table = self.database.get_table(name)
            except Exception:
                # Denied or unresolvable for this caller — leave it out of the catalog entirely.
                continue

            table_type, table_schema = _classify_table(name, table, self.warehouse, self.views)
            row_count = self._row_count(name, table, table_type)
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


def _introspect(
    context: "HogQLContext", allowed_tables: Optional[frozenset[str]] = None
) -> tuple[list[list[Any]], list[list[Any]], list[list[Any]]]:
    """Introspect the database once per (query, pushdown filter), reusing the result across tables.

    A query that joins several information_schema tables would otherwise rebuild the full
    introspection — including the warehouse-metadata ORM queries — once per referenced table. The
    cache is keyed by the pushed-down `allowed_tables` set so a filtered scan walks only the tables
    it needs while still sharing work between references that resolve to the same bound.
    """
    cache = context.information_schema_introspection
    if cache is None:
        cache = context.information_schema_introspection = {}
    if allowed_tables not in cache:
        database = context.database
        cache[allowed_tables] = (
            _Introspection(database, context, allowed_tables).collect() if database is not None else ([], [], [])
        )
    return cache[allowed_tables]


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
        allowed = _pushdown_table_filter(node, "table_name")
        table_rows, _, _ = _introspect(context, allowed)
        return _rows_select(context, "tables", _TABLES_COLUMNS, table_rows, allowed)

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
        allowed = _pushdown_table_filter(node, "table_name")
        _, column_rows, _ = _introspect(context, allowed)
        return _rows_select(context, "columns", _COLUMNS_COLUMNS, column_rows, allowed)

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
        allowed = _pushdown_table_filter(node, "source_table")
        _, _, relationship_rows = _introspect(context, allowed)
        return _rows_select(context, "relationships", _RELATIONSHIPS_COLUMNS, relationship_rows, allowed)

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
