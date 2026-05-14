"""Shared helpers for projecting HogQL `system.*` tables into the catalog.

Two call sites depend on the same enumeration logic:
  - `temporal/activities/enumerate.py::enumerate_system_tables` (per-team, via the
    cron-driven traversal workflow)
  - `logic.py::sync_system_tables_for_team` (per-team, called synchronously from
    the Team post_save signal and the seed_system_catalog management command)

Keep the projection in one place so both call sites agree on what counts as a
column and how DatabaseField classes map to ClickHouse type strings.
"""

from collections.abc import Iterator

from posthog.hogql.database.models import DatabaseField, ExpressionField, Table
from posthog.hogql.database.schema.system import SystemTables

_HOGQL_TYPE_MAP: dict[str, str] = {
    "IntegerDatabaseField": "Int",
    "FloatDatabaseField": "Float",
    "DecimalDatabaseField": "Decimal",
    "StringDatabaseField": "String",
    "UnknownDatabaseField": "Unknown",
    "StringJSONDatabaseField": "JSON",
    "StructDatabaseField": "Struct",
    "StringArrayDatabaseField": "Array(String)",
    "FloatArrayDatabaseField": "Array(Float)",
    "DateDatabaseField": "Date",
    "DateTimeDatabaseField": "DateTime",
    "BooleanDatabaseField": "Boolean",
    "UUIDDatabaseField": "UUID",
    # ExpressionField wraps an `ast.Call(name="toInt", ...)` everywhere in
    # system.py — surface it as Int so downstream consumers don't see
    # "ExpressionField" as a type.
    "ExpressionField": "Int",
}


def field_to_clickhouse_type(field: DatabaseField) -> str:
    return _HOGQL_TYPE_MAP.get(type(field).__name__, type(field).__name__)


class SystemColumn:
    __slots__ = ("name", "clickhouse_type", "nullable")

    def __init__(self, name: str, clickhouse_type: str, nullable: bool) -> None:
        self.name = name
        self.clickhouse_type = clickhouse_type
        self.nullable = nullable


def iter_system_table_columns(table: Table) -> Iterator[SystemColumn]:
    """Yield one SystemColumn per visible (non-hidden) DatabaseField on `table`.

    ExpressionField aliases (e.g. `paused` on `batch_exports`) are visible; their
    `_paused` raw counterparts are hidden and skipped. Joins, lazy tables, and
    FieldTraversers are not DatabaseField and are skipped.
    """
    for name, descriptor in (table.fields or {}).items():
        if not isinstance(descriptor, DatabaseField):
            continue
        if descriptor.hidden:
            continue
        nullable = descriptor.is_nullable() if not isinstance(descriptor, ExpressionField) else False
        yield SystemColumn(name=name, clickhouse_type=field_to_clickhouse_type(descriptor), nullable=nullable)


def iter_system_tables() -> Iterator[tuple[str, Table]]:
    """Yield `(name, table)` pairs for every entry in SystemTables.children.

    SystemTables is a Pydantic model — `children` is a field default that only
    materializes on an instance, not on the class itself.
    """
    for name, child in SystemTables().children.items():
        if not isinstance(child.table, Table):
            continue
        yield name, child.table
