"""HogQL `information_schema`: a self-describing, queryable view of the database catalog.

Nested under the `system` namespace, these virtual tables let agents (and humans) discover what
tables, columns, data types, relationships, and descriptions are available without leaving HogQL:

    SELECT * FROM system.information_schema.columns WHERE table_name = 'events'
    SELECT * FROM system.information_schema.relationships WHERE source_table = 'events'

The rows are computed at query time from the live, per-team `Database` object, so they always
reflect the caller's own access (denied/hidden tables never appear). Descriptions are resolved
through the shared `TableDescriptions` layer — static `FieldOrTable.description`, plus the
`WarehouseColumnAnnotation` (warehouse tables) and `DataWarehouseSavedQueryColumnAnnotation` (views)
semantic layers — fetched lazily only when these tables are queried.
"""

import json
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
from posthog.hogql.database.schema.table_descriptions import TableDescriptions
from posthog.hogql.errors import BaseHogQLError

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
_NULLABLE_FLOAT = "nullable_float"
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
    if kind == _NULLABLE_FLOAT:
        return ast.Call(name="accurateCastOrNull", args=[source, ast.Constant(value="Float64")])
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


def _capture_unexpected(message: str, error: Exception) -> None:
    """Surface a genuinely-unexpected resolution failure (a bug, not an unresolvable field) to error
    tracking — expected `BaseHogQLError`s are handled by the caller and never sent here."""
    # Deferred: keeps the (heavier) capture dependency off this schema module's import path.
    from posthog.exceptions_capture import capture_exception  # noqa: PLC0415

    tracking_error = Exception(message)
    tracking_error.__cause__ = error
    capture_exception(tracking_error)


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
    # The `posthog.*` namespace holds two kinds of tables: copies of the top-level tables
    # (`posthog.events`, `posthog.persons`, …) and data-plane tables that live *only* there
    # (`posthog.ai_events`, `posthog.trace_spans`, `posthog.metrics`, the web pre-aggregated
    # tables, …). Hide the copies to keep the catalog clean, but keep the unique ones — they're
    # queryable by their `posthog.`-qualified name (a bare `FROM ai_events` errors), so leaving
    # them out makes them undiscoverable through the schema-discovery workflow. Everything else
    # (built-in, system, warehouse, views) is included.
    names = database.tables.resolve_visible_table_names()
    root_names = {n for n in names if "." not in n}
    return [n for n in names if not (n.startswith("posthog.") and n[len("posthog.") :] in root_names)]


# Per-column statistics surfaced into information_schema.columns: (null_fraction, min_value, max_value).
_ColumnStats = tuple[Optional[float], Optional[str], Optional[str]]
_RelationshipProvenanceKey = tuple[str, str, str, str, str]


def _warehouse_metadata(
    team_id: Optional[int],
) -> tuple[dict[str, Optional[int]], dict[str, Optional[int]], dict[tuple[str, str], _ColumnStats]]:
    """Lazily load warehouse row counts and column statistics for the team.

    Returns `(row_counts, view_row_counts, column_stats)`. `row_counts` is keyed by warehouse table
    name, `view_row_counts` by saved-query (view) name. `column_stats` is keyed by
    `(table_id, column_name)` and carries `(null_fraction, min_value, max_value)` from the Delta-log
    profiling. Descriptions are resolved separately via `TableDescriptions`. Only runs when an
    information_schema table is actually queried, so it never touches the hot `create_hogql_database`
    path. Mirrors how `serialize_database` sources counts so the catalog and the SQL-editor schema
    agree.
    """
    row_counts: dict[str, Optional[int]] = {}
    view_row_counts: dict[str, Optional[int]] = {}
    column_stats: dict[tuple[str, str], _ColumnStats] = {}
    if team_id is None:
        return row_counts, view_row_counts, column_stats

    # Inline imports: keeps the products dependency off the hogql import path (avoids an import
    # cycle, since products import hogql) and off every non-information_schema query.
    from posthog.models.scoping import team_scope  # noqa: PLC0415

    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery  # noqa: PLC0415
    from products.warehouse_sources.backend.facade.models import (  # noqa: PLC0415
        DataWarehouseTable,
        WarehouseColumnStatistics,
    )

    try:
        with team_scope(team_id):
            # `DataWarehouseTable` is on the IDOR baseline (not team-scoped), so `team_scope` is a
            # no-op for it — filter by team_id explicitly or it reads every team's tables. `.queryable()`
            # (not `.objects`) drops soft-deleted tables and orphans of a soft-deleted source —
            # otherwise a re-synced table's dead duplicate clobbers the live row_count with a stale/null
            # value. Oldest first so the newest row wins a name collision, matching the last-write-wins
            # order `serialize_database` uses.
            for table_name, row_count in (
                DataWarehouseTable.objects.queryable()
                .filter(team_id=team_id)
                .order_by("created_at")
                .values_list("name", "row_count")
            ):
                row_counts[table_name] = row_count
            # Views carry their row count on the materialized backing table (`saved_query.table`).
            for view_name, row_count in (
                DataWarehouseSavedQuery.objects.exclude(deleted=True)
                .filter(team_id=team_id, table__isnull=False)
                .values_list("name", "table__row_count")
            ):
                view_row_counts[view_name] = row_count
            # Per-column profiling stats (keyed by table UUID + column). Only the columns that have been
            # profiled appear; everything else stays absent (NULL in the catalog).
            for (
                table_id,
                column_name,
                null_fraction,
                min_value,
                max_value,
            ) in WarehouseColumnStatistics.objects.values_list(
                "table_id", "column_name", "null_fraction", "min_value", "max_value"
            ):
                column_stats[(str(table_id), column_name)] = (null_fraction, min_value, max_value)
    except Exception:
        # Schema discovery must never fail a query because the warehouse metadata could not be read,
        # but log so a transient DB error can be told apart from a real bug in the fetch loop.
        logger.exception("information_schema: failed to load warehouse metadata", team_id=team_id)
        return {}, {}, {}

    return row_counts, view_row_counts, column_stats


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
    _NULLABLE_FLOAT: "Nullable(Float64)",
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
    if kind == _NULLABLE_FLOAT:
        return FloatDatabaseField(name=name, nullable=True)
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
        # Non-cryptographic: just a stable, collision-resistant suffix for the table name.
        suffix = "f" + hashlib.sha256("\x01".join(sorted(allowed)).encode()).hexdigest()[:12]
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
        self.context = context
        self.allowed_tables = allowed_tables
        self.warehouse = set(database.get_warehouse_table_names())
        self.views = set(database.get_view_names())
        self.row_counts, self.view_row_counts, self.column_stats = _warehouse_metadata(context.team_id)
        self.table_descriptions = TableDescriptions.load(context.team_id)
        self._collected: Optional[tuple[list[list[Any]], list[list[Any]], list[list[Any]]]] = None
        self._relationship_provenance_keys: list[Optional[_RelationshipProvenanceKey]] = []
        # Resolved `SELECT * FROM <table>` scope per table, so expression columns can be typed without
        # re-resolving the table once per expression.
        self._table_scope_cache: dict[str, Optional[ast.SelectQueryType]] = {}

    def _data_type(self, table_name: str, field: DatabaseField) -> str:
        if isinstance(field, ExpressionField):
            return self._expression_data_type(table_name, field)
        return _field_type_name(field)

    def _table_scope(self, table_name: str) -> Optional["ast.SelectQueryType"]:
        if table_name not in self._table_scope_cache:
            # Deferred: resolver imports the schema package, so a module-level import would cycle.
            from posthog.hogql.resolver import resolve_table_scope  # noqa: PLC0415

            scope: Optional[ast.SelectQueryType] = None
            try:
                scope = resolve_table_scope(table_name.replace("`", "").split("."), self.context, "hogql")
            except BaseHogQLError:
                scope = None  # genuinely unresolvable table — expected, fall back quietly
            except Exception as e:
                _capture_unexpected("information_schema: failed to resolve table scope", e)
            self._table_scope_cache[table_name] = scope
        return self._table_scope_cache[table_name]

    def _expression_data_type(self, table_name: str, field: ExpressionField) -> str:
        """Type an expression column by the value it evaluates to, like the HogQL autocomplete does;
        fall back to the generic "Expression" if it can't be resolved."""
        scope = self._table_scope(table_name)
        if scope is None:
            return "Expression"
        # Deferred: see `_table_scope`.
        from posthog.hogql.resolver import resolve_types  # noqa: PLC0415
        from posthog.hogql.visitor import clone_expr  # noqa: PLC0415

        try:
            # Clone so resolution never mutates the shared schema field's expression.
            resolved = resolve_types(clone_expr(field.expr, clear_locations=True), self.context, "hogql", [scope])
            if resolved.type is None:
                return "Expression"
            return resolved.type.resolve_constant_type(self.context).print_type()
        except BaseHogQLError:
            return "Expression"  # genuinely unresolvable expression — expected
        except Exception as e:
            _capture_unexpected("information_schema: failed to resolve expression column type", e)
            return "Expression"

    def _row_count(self, name: str, table: Table, table_type: str) -> Optional[int]:
        if table_type == "data_warehouse" and table.name:
            return self.row_counts.get(table.name)
        if table_type == "view":
            # Views are keyed by their catalog name (the saved-query name), which is `name` here.
            return self.view_row_counts.get(name)
        return None

    def _table_description(self, table: Table) -> Optional[str]:
        return self.table_descriptions.for_table(table)

    def _column_description(self, table: Table, column_name: str, field: FieldOrTable) -> Optional[str]:
        return self.table_descriptions.for_column(table, column_name, field)

    def _column_stats(self, table: Table, table_type: str, column_name: str) -> _ColumnStats:
        """`(null_fraction, min_value, max_value)` for a warehouse column, or all-None otherwise."""
        if table_type == "data_warehouse":
            table_id = getattr(table, "table_id", None)
            if table_id:
                return self.column_stats.get((str(table_id), column_name), (None, None, None))
        return (None, None, None)

    def collect(self) -> tuple[list[list[Any]], list[list[Any]], list[list[Any]]]:
        if self._collected is not None:
            return self._collected

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
            table_rows.append([name, table_schema, name, table_type, self._table_description(table), row_count])

            self._collect_fields(
                name,
                table_schema,
                table_type,
                table,
                table.fields,
                column_rows,
                relationship_rows,
                self._relationship_provenance_keys,
            )

        self._collected = (table_rows, column_rows, relationship_rows)
        return self._collected

    def table_rows(self) -> list[list[Any]]:
        table_rows, _, _ = self.collect()
        certifications = _catalog_certifications(self.context, self.allowed_tables)
        return [[*row, certifications.get(row[2])] for row in table_rows]

    def column_rows(self) -> list[list[Any]]:
        _, column_rows, _ = self.collect()
        return column_rows

    def relationship_rows(self) -> list[list[Any]]:
        _, _, relationship_rows = self.collect()
        accepted_relationships = _catalog_accepted_relationships(self.context, self.allowed_tables)
        enriched_rows: list[list[Any]] = []
        for row, provenance_key in zip(relationship_rows, self._relationship_provenance_keys, strict=True):
            confidence, reasoning = accepted_relationships.get(provenance_key, (None, None))
            enriched_rows.append([*row[:7], confidence, reasoning])
        enriched_rows.extend(_catalog_proposed_relationships(self.context, self.allowed_tables))
        return enriched_rows

    def _collect_fields(
        self,
        table_name: str,
        table_schema: str,
        table_type: str,
        table: Table,
        fields: dict[str, FieldOrTable],
        column_rows: list[list[Any]],
        relationship_rows: list[list[Any]],
        relationship_provenance_keys: list[Optional[_RelationshipProvenanceKey]],
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
                null_fraction, min_value, max_value = self._column_stats(table, table_type, qualified)
                column_rows.append(
                    [
                        table_schema,
                        table_name,
                        qualified,
                        ordinal,
                        self._data_type(table_name, field),
                        bool(field.is_nullable()),
                        bool(field.array),
                        kind,
                        self._column_description(table, qualified, field),
                        null_fraction,
                        min_value,
                        max_value,
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
                        "active",
                        None,
                        None,
                    ]
                )
                relationship_provenance_keys.append(_relationship_provenance_key(table_name, field_name, field))
            elif isinstance(field, FieldTraverser):
                relationship_rows.append(
                    [
                        table_name,
                        qualified,
                        table_name,
                        ".".join(str(x) for x in field.chain),
                        "field_traverser",
                        None,
                        "active",
                        None,
                        None,
                    ]
                )
                relationship_provenance_keys.append(None)
            elif isinstance(field, VirtualTable):
                # Surface nested virtual-table columns as `parent.child` columns.
                column_rows.append(
                    [
                        table_schema,
                        table_name,
                        qualified,
                        ordinal,
                        "VirtualTable",
                        False,
                        False,
                        "virtual_table",
                        None,
                        None,
                        None,
                        None,
                    ]
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
                    relationship_provenance_keys,
                    prefix=f"{qualified}.",
                    ordinal_start=ordinal,
                )

        return ordinal


def _relationship_provenance_key(
    table_name: str, field_name: str, field: LazyJoin
) -> Optional[_RelationshipProvenanceKey]:
    resolver_params = field.resolver_params
    source_table_key = resolver_params.get("source_table_key")
    joining_table_name = resolver_params.get("joining_table_name")
    joining_table_key = resolver_params.get("joining_table_key")
    if (
        not isinstance(source_table_key, str)
        or not isinstance(joining_table_name, str)
        or not isinstance(joining_table_key, str)
    ):
        return None
    return (table_name, field_name, source_table_key, joining_table_name, joining_table_key)


def _introspection(
    context: "HogQLContext", allowed_tables: Optional[frozenset[str]] = None
) -> Optional[_Introspection]:
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
        cache[allowed_tables] = _Introspection(database, context, allowed_tables) if database is not None else None
    return cache[allowed_tables]


# --- the virtual tables ----------------------------------------------------------------------- #

_TABLES_COLUMNS: list[tuple[str, str]] = [
    ("table_catalog", _STRING),
    ("table_schema", _STRING),
    ("table_name", _STRING),
    ("table_type", _STRING),
    ("description", _NULLABLE_STRING),
    ("row_count", _NULLABLE_INTEGER),
    ("certification", _NULLABLE_STRING),
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
    ("null_fraction", _NULLABLE_FLOAT),
    ("min_value", _NULLABLE_STRING),
    ("max_value", _NULLABLE_STRING),
]

_RELATIONSHIPS_COLUMNS: list[tuple[str, str]] = [
    ("source_table", _STRING),
    ("source_column", _STRING),
    ("target_table", _STRING),
    ("target_column", _NULLABLE_STRING),
    ("relationship_kind", _STRING),
    ("via", _NULLABLE_STRING),
    ("status", _STRING),
    ("confidence", _NULLABLE_FLOAT),
    ("reasoning", _NULLABLE_STRING),
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


_METRICS_COLUMNS: list[tuple[str, str]] = [
    ("id", _STRING),
    ("name", _STRING),
    ("display_name", _NULLABLE_STRING),
    ("description", _STRING),
    ("unit", _NULLABLE_STRING),
    ("status", _STRING),
    ("is_drifted", _BOOLEAN),
    ("definition", _NULLABLE_STRING),
    ("definition_kind", _NULLABLE_STRING),
    ("owner", _NULLABLE_STRING),
    ("confidence", _NULLABLE_FLOAT),
    ("reasoning", _NULLABLE_STRING),
    ("source_insight_short_id", _NULLABLE_STRING),
    ("last_run_at", _NULLABLE_STRING),
    ("created_at", _STRING),
]


def _references_denied_table(referenced_table_names: Optional[list[str]], denied: set[str]) -> bool:
    """Whether any of a metric's referenced tables is in the caller's denied set.

    `referenced_table_names` stores the surface identifier the author typed (bare `charges` or dotted
    `stripe.charges`, any case), while `_denied_tables` holds a mix of bare names, lowercased
    qualified warehouse keys, and `system.<name>`. Match case-insensitively and by leaf so a
    qualified reference to a bare-denied table (or the reverse) still trips the denial — err toward
    hiding rather than leaking a metric whose source the caller cannot read.
    """
    if not denied or not referenced_table_names:
        return False
    denied_norm = {name.lower() for name in denied}
    denied_norm |= {name.rsplit(".", 1)[-1] for name in denied_norm}
    for name in referenced_table_names:
        normalized = name.lower()
        if normalized in denied_norm or normalized.rsplit(".", 1)[-1] in denied_norm:
            return True
    return False


def _can_read_catalog(context: "HogQLContext") -> bool:
    """Whether the caller has data_catalog read access, mirroring the REST viewset's resource gate.

    Metric rows carry governed definitions and free-text review context, so — like the metric-run and
    proposal-accept endpoints — they need an explicit `data_catalog` resource check, not just team
    scoping. Fails closed when there's no access-control context (service tokens / shared links),
    matching warehouse-table denial.
    """
    access_control = context.database.user_access_control if context.database is not None else None
    if access_control is None:
        access_control = context.user_access_control
    if access_control is None:
        return False
    return access_control.check_access_level_for_resource("data_catalog", "viewer")


def _catalog_metrics(context: "HogQLContext", allowed: Optional[frozenset[str]]) -> list[list[Any]]:
    """Load the team's catalog metrics as information_schema rows (fail-soft).

    Returns nothing unless the caller has data_catalog read access; hides metrics whose definition
    references a table the caller is denied, and computes drift in one bulk pass shared with the REST
    serializer.
    """
    team_id = context.team_id
    if team_id is None or not _can_read_catalog(context):
        return []
    # Deferred + facade-only imports: keep the product's (heavy) query-runner deps off this schema
    # module's import path, and respect the data_catalog isolation boundary.
    from products.data_catalog.backend.facade.api import compute_drift  # noqa: PLC0415
    from products.data_catalog.backend.facade.models import Metric  # noqa: PLC0415

    try:
        denied = context.database._denied_tables if context.database is not None else set()
        queryset = (
            Metric.objects.for_team(team_id).filter(deleted=False).select_related("owner").order_by("-created_at")
        )
        if allowed is not None:
            queryset = queryset.filter(name__in=allowed)
        metrics = list(queryset)
        drift = compute_drift(metrics)
        rows: list[list[Any]] = []
        for metric in metrics:
            if _references_denied_table(metric.referenced_table_names, denied):
                continue
            rows.append(
                [
                    str(metric.id),
                    metric.name,
                    metric.display_name,
                    metric.description,
                    metric.unit,
                    metric.status,
                    drift.get(metric.id, False),
                    json.dumps(metric.definition) if metric.definition else None,
                    metric.definition_kind,
                    metric.owner.email if metric.owner else None,
                    metric.confidence,
                    metric.reasoning,
                    metric.source_insight_short_id,
                    metric.last_run_at.isoformat() if metric.last_run_at else None,
                    metric.created_at.isoformat(),
                ]
            )
        return rows
    except Exception:
        logger.exception("information_schema: failed to load catalog metrics", team_id=team_id)
        return []


def _catalog_certifications(context: "HogQLContext", allowed: Optional[frozenset[str]]) -> dict[str, str]:
    """Map each certified/deprecated table or view name to its certification status (fail-soft).

    Certifications live directly on the table/view, so no backing-table remap is needed. Soft-deleted
    targets are excluded (their marks read as absent).
    """
    team_id = context.team_id
    if team_id is None or not _can_read_catalog(context):
        return {}
    from products.data_catalog.backend.facade.enums import CertificationStatus  # noqa: PLC0415
    from products.data_catalog.backend.facade.models import TableCertification  # noqa: PLC0415

    try:
        result: dict[str, str] = {}
        certs = TableCertification.objects.for_team(team_id).filter(
            status__in=(CertificationStatus.CERTIFIED, CertificationStatus.DEPRECATED)
        )
        table_certs = (
            certs.filter(table__isnull=False)
            .exclude(table__deleted=True)
            .exclude(table__external_data_source__deleted=True)
        )
        view_certs = certs.filter(saved_query__isnull=False).exclude(saved_query__deleted=True)
        if allowed is not None:
            table_certs = table_certs.filter(table__name__in=allowed)
            view_certs = view_certs.filter(saved_query__name__in=allowed)
        for name, status in table_certs.values_list("table__name", "status"):
            result[name] = status
        for name, status in view_certs.values_list("saved_query__name", "status"):
            result[name] = status
        return result
    except Exception:
        logger.exception("information_schema: failed to load certifications", team_id=team_id)
        return {}


def _catalog_table_visible(context: "HogQLContext", table_name: str) -> bool:
    database = context.database
    if database is None or _references_denied_table([table_name], database._denied_tables):
        return False
    try:
        return database.has_table(table_name) and database.get_table(table_name) is not None
    except Exception:
        return False


def _catalog_proposed_relationships(context: "HogQLContext", allowed: Optional[frozenset[str]]) -> list[list[Any]]:
    """Proposed/rejected relationship proposals, surfaced as proposed_join rows (fail-soft).

    Accepted proposals are not returned here: they already exist as real lazy_join rows, enriched with
    their confidence/reasoning via `_catalog_accepted_relationships`.
    """
    team_id = context.team_id
    if team_id is None or not _can_read_catalog(context):
        return []
    from products.data_catalog.backend.facade.enums import RelationshipStatus  # noqa: PLC0415
    from products.data_catalog.backend.facade.models import RelationshipProposal  # noqa: PLC0415

    try:
        proposals = RelationshipProposal.objects.for_team(team_id).exclude(status=RelationshipStatus.ACCEPTED)
        if allowed is not None:
            proposals = proposals.filter(source_table_name__in=allowed)
        rows: list[list[Any]] = []
        for source_table, source_key, target_table, target_key, status, confidence, reasoning in proposals.values_list(
            "source_table_name",
            "source_table_key",
            "joining_table_name",
            "joining_table_key",
            "status",
            "confidence",
            "reasoning",
        ):
            if not _catalog_table_visible(context, source_table) or not _catalog_table_visible(context, target_table):
                continue
            rows.append(
                [
                    source_table,
                    source_key,
                    target_table,
                    target_key,
                    "proposed_join",
                    None,
                    status,
                    confidence,
                    reasoning or None,
                ]
            )
        return rows
    except Exception:
        logger.exception("information_schema: failed to load relationship proposals", team_id=team_id)
        return []


def _catalog_accepted_relationships(
    context: "HogQLContext", allowed: Optional[frozenset[str]]
) -> dict[_RelationshipProvenanceKey, tuple[Optional[float], Optional[str]]]:
    """Accepted proposals keyed by their active created join's full identity (fail-soft)."""
    team_id = context.team_id
    if team_id is None or not _can_read_catalog(context):
        return {}
    from products.data_catalog.backend.facade.enums import RelationshipStatus  # noqa: PLC0415
    from products.data_catalog.backend.facade.models import RelationshipProposal  # noqa: PLC0415

    try:
        accepted = RelationshipProposal.objects.for_team(team_id).filter(
            status=RelationshipStatus.ACCEPTED,
            created_join__isnull=False,
            created_join__deleted=False,
        )
        if allowed is not None:
            accepted = accepted.filter(created_join__source_table_name__in=allowed)
        result: dict[_RelationshipProvenanceKey, tuple[Optional[float], Optional[str]]] = {}
        for (
            source_table,
            field_name,
            source_key,
            target_table,
            target_key,
            confidence,
            reasoning,
        ) in accepted.values_list(
            "created_join__source_table_name",
            "created_join__field_name",
            "created_join__source_table_key",
            "created_join__joining_table_name",
            "created_join__joining_table_key",
            "confidence",
            "reasoning",
        ):
            if not _catalog_table_visible(context, source_table) or not _catalog_table_visible(context, target_table):
                continue
            result[(source_table, field_name, source_key, target_table, target_key)] = (
                confidence,
                reasoning or None,
            )
        return result
    except Exception:
        logger.exception("information_schema: failed to load accepted relationships", team_id=team_id)
        return {}


def _string_field(name: str, nullable: bool = False, description: Optional[str] = None) -> StringDatabaseField:
    return StringDatabaseField(name=name, nullable=nullable, description=description)


class InformationSchemaTablesTable(LazyTable):
    description: str = (
        "SQL-standard catalog of every table, view, system table, and data warehouse table visible "
        "to the caller; one row per table. Start here to discover what is queryable."
    )
    fields: dict[str, FieldOrTable] = {
        "table_catalog": _string_field(
            "table_catalog",
            nullable=False,
            description="Table name (same as table_name); PostHog does not use a separate catalog identifier.",
        ),
        "table_schema": _string_field(
            "table_schema",
            nullable=False,
            description="Schema bucket the table sits in: 'public', 'system', 'information_schema', 'warehouse', or 'views'.",
        ),
        "table_name": _string_field("table_name", nullable=False, description="The table's name, used to query it."),
        "table_type": _string_field(
            "table_type",
            nullable=False,
            description="Origin of the table: 'posthog', 'system', 'information_schema', 'data_warehouse', or 'view'.",
        ),
        "description": _string_field(
            "description", nullable=True, description="Human/agent-facing description of what the table holds."
        ),
        "row_count": IntegerDatabaseField(
            name="row_count",
            nullable=True,
            description="Approximate row count; only populated for data warehouse tables and views, NULL otherwise.",
        ),
        "certification": _string_field(
            "certification",
            nullable=True,
            description="Trust mark: 'certified' (prefer this source), 'deprecated' (avoid it), or NULL (unmarked).",
        ),
    }

    def lazy_select(self, table_to_add: LazyTableToAdd, context: "HogQLContext", node: Any) -> ast.SelectQuery:
        allowed = _pushdown_table_filter(node, "table_name")
        introspection = _introspection(context, allowed)
        table_rows = introspection.table_rows() if introspection is not None else []
        return _rows_select(context, "tables", _TABLES_COLUMNS, table_rows, allowed)

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return "information_schema.tables"

    def to_printed_hogql(self) -> str:
        return "system__information_schema__tables"


class InformationSchemaColumnsTable(LazyTable):
    description: str = (
        "SQL-standard catalog of every column on every visible table; one row per column. Filter by "
        "table_name to inspect a table's columns, their types, descriptions, and (for data warehouse "
        "tables) profiling statistics: null_fraction, min_value, max_value."
    )
    fields: dict[str, FieldOrTable] = {
        "table_schema": _string_field(
            "table_schema", nullable=False, description="Schema bucket the column's table belongs to."
        ),
        "table_name": _string_field(
            "table_name", nullable=False, description="Name of the table the column belongs to."
        ),
        "column_name": _string_field(
            "column_name",
            nullable=False,
            description="Column name; nested virtual-table columns appear as 'parent.child'.",
        ),
        "ordinal_position": IntegerDatabaseField(
            name="ordinal_position", nullable=False, description="1-based position of the column within its table."
        ),
        "data_type": _string_field(
            "data_type",
            nullable=False,
            description="HogQL data type, e.g. String, Integer, DateTime, JSON; see information_schema.data_types.",
        ),
        "is_nullable": BooleanDatabaseField(
            name="is_nullable", nullable=False, description="Whether the column can hold NULL values."
        ),
        "is_array": BooleanDatabaseField(
            name="is_array", nullable=False, description="Whether the column is an array type."
        ),
        "field_kind": _string_field(
            "field_kind",
            nullable=False,
            description="How the column is backed: 'column', 'expression' (computed), or 'virtual_table'.",
        ),
        "description": _string_field(
            "description", nullable=True, description="Human/agent-facing description of what the column holds."
        ),
        "null_fraction": FloatDatabaseField(
            name="null_fraction",
            nullable=True,
            description=(
                "Fraction of values that are NULL (0.0–1.0), from data warehouse column statistics. "
                "Use it to avoid or special-case null-heavy columns. NULL for non-warehouse tables and "
                "for warehouse columns not yet profiled."
            ),
        ),
        "min_value": _string_field(
            "min_value",
            nullable=True,
            description=(
                "Minimum value observed in this column (from the Delta-log statistics), as a string. "
                "Use it to bound range and time-window filters. NULL when unprofiled or not applicable."
            ),
        ),
        "max_value": _string_field(
            "max_value",
            nullable=True,
            description=(
                "Maximum value observed in this column (from the Delta-log statistics), as a string. "
                "Use it to bound range and time-window filters. NULL when unprofiled or not applicable."
            ),
        ),
    }

    def lazy_select(self, table_to_add: LazyTableToAdd, context: "HogQLContext", node: Any) -> ast.SelectQuery:
        allowed = _pushdown_table_filter(node, "table_name")
        introspection = _introspection(context, allowed)
        column_rows = introspection.column_rows() if introspection is not None else []
        return _rows_select(context, "columns", _COLUMNS_COLUMNS, column_rows, allowed)

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return "information_schema.columns"

    def to_printed_hogql(self) -> str:
        return "system__information_schema__columns"


class InformationSchemaRelationshipsTable(LazyTable):
    description: str = (
        "Joinable relationships between tables; one row per relationship. Active joins (lazy_join / "
        "field_traverser) plus reviewed catalog join proposals (relationship_kind='proposed_join'). "
        "Prefer active joins; a 'rejected' proposal was reviewed and should not be used."
    )
    fields: dict[str, FieldOrTable] = {
        "source_table": _string_field(
            "source_table", nullable=False, description="Table the relationship is defined on."
        ),
        "source_column": _string_field(
            "source_column", nullable=False, description="Column (or field path) on the source table that joins out."
        ),
        "target_table": _string_field("target_table", nullable=False, description="Table the relationship points to."),
        "target_column": _string_field(
            "target_column", nullable=True, description="Column (or field path) on the target table that is joined to."
        ),
        "relationship_kind": _string_field(
            "relationship_kind",
            nullable=False,
            description="'lazy_join', 'field_traverser', or 'proposed_join' (a reviewed catalog proposal).",
        ),
        "via": _string_field(
            "via", nullable=True, description="Internal resolver backing a lazy join, NULL otherwise."
        ),
        "status": _string_field(
            "status",
            nullable=False,
            description="'active' for real joins; 'proposed'/'rejected' for catalog proposals not yet promoted.",
        ),
        "confidence": FloatDatabaseField(
            name="confidence",
            nullable=True,
            description="Discovery confidence for a proposed join or the accepted proposal behind an active join, 0-1.",
        ),
        "reasoning": _string_field(
            "reasoning",
            nullable=True,
            description="Why a join was proposed; retained on the active join after acceptance.",
        ),
    }

    def lazy_select(self, table_to_add: LazyTableToAdd, context: "HogQLContext", node: Any) -> ast.SelectQuery:
        allowed = _pushdown_table_filter(node, "source_table")
        introspection = _introspection(context, allowed)
        relationship_rows = introspection.relationship_rows() if introspection is not None else []
        return _rows_select(context, "relationships", _RELATIONSHIPS_COLUMNS, relationship_rows, allowed)

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return "information_schema.relationships"

    def to_printed_hogql(self) -> str:
        return "system__information_schema__relationships"


class InformationSchemaDataTypesTable(LazyTable):
    description: str = (
        "Reference list of the HogQL data types reported in information_schema.columns, with a short "
        "explanation of each; one row per type."
    )
    fields: dict[str, FieldOrTable] = {
        "type_name": _string_field(
            "type_name", nullable=False, description="Type name as it appears in columns.data_type."
        ),
        "description": _string_field("description", nullable=False, description="What values of this type represent."),
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


class InformationSchemaMetricsTable(LazyTable):
    description: str = (
        "Catalog of the project's governed business metrics (the semantic layer); one row per metric. "
        "Consult only when the user asks for a named headline business number (MRR, activation, etc.) — "
        "only a metric with status='approved' AND NOT is_drifted is canonical; use its definition instead "
        "of re-deriving. Usually empty; an empty result just means no governed definition, so derive "
        "the number normally. Filter by name (equality or IN)."
    )
    fields: dict[str, FieldOrTable] = {
        "id": _string_field("id", description="Stable UUID of the metric (cross-reference for the REST API)."),
        "name": _string_field(
            "name", description="Identifier-safe handle uniquely naming this metric within the project."
        ),
        "display_name": _string_field("display_name", nullable=True, description="Human-friendly label."),
        "description": _string_field("description", description="What the metric means and how to interpret it."),
        "unit": _string_field("unit", nullable=True, description="Unit of the result, e.g. usd, percent, cents."),
        "status": _string_field(
            "status", description="'proposed' or 'approved'. Never cite a proposed metric as canonical."
        ),
        "is_drifted": BooleanDatabaseField(
            name="is_drifted",
            nullable=False,
            description="True if the definition drifted from its source insight (or the insight is gone). Do not trust a drifted metric.",
        ),
        "definition": _string_field(
            "definition",
            nullable=True,
            description="Machine-readable query as JSON, or NULL for a name+description-only stub.",
        ),
        "definition_kind": _string_field(
            "definition_kind",
            nullable=True,
            description="Query kind: HogQLQuery, TrendsQuery, FunnelsQuery, or an event node.",
        ),
        "owner": _string_field("owner", nullable=True, description="Email of the human accountable for this metric."),
        "confidence": FloatDatabaseField(
            name="confidence", nullable=True, description="AI author's confidence for a proposed metric, 0-1."
        ),
        "reasoning": _string_field("reasoning", nullable=True, description="AI author's reasoning, review context."),
        "source_insight_short_id": _string_field(
            "source_insight_short_id",
            nullable=True,
            description="Short ID of the insight this metric was created from.",
        ),
        "last_run_at": _string_field(
            "last_run_at", nullable=True, description="ISO timestamp of the last run (throttled)."
        ),
        "created_at": _string_field("created_at", description="ISO timestamp when the metric was created."),
    }

    def lazy_select(self, table_to_add: LazyTableToAdd, context: "HogQLContext", node: Any) -> ast.SelectQuery:
        allowed = _pushdown_table_filter(node, "name")
        return _rows_select(context, "metrics", _METRICS_COLUMNS, _catalog_metrics(context, allowed), allowed)

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return "information_schema.metrics"

    def to_printed_hogql(self) -> str:
        return "system__information_schema__metrics"


def information_schema_node() -> TableNode:
    """The `information_schema` namespace, mounted under `system` (see `SystemTables.children`)."""
    return TableNode(
        name="information_schema",
        children={
            "tables": TableNode(name="tables", table=InformationSchemaTablesTable()),
            "columns": TableNode(name="columns", table=InformationSchemaColumnsTable()),
            "relationships": TableNode(name="relationships", table=InformationSchemaRelationshipsTable()),
            "data_types": TableNode(name="data_types", table=InformationSchemaDataTypesTable()),
            "metrics": TableNode(name="metrics", table=InformationSchemaMetricsTable()),
        },
    )
