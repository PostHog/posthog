from __future__ import annotations

from typing import TYPE_CHECKING

from posthog.hogql.database.direct_trino_table import DirectTrinoTable
from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.errors import QueryError

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.database.models import Table


TrinoTableLocator = tuple[str, str, str]

TRINO_EXPORTED_POSTHOG_TABLES = frozenset({"events", "persons", "groups", "raw_groups"})
_EXPORTED_POSTHOG_TABLE_SCANS = TRINO_EXPORTED_POSTHOG_TABLES | {"raw_persons"}


def resolve_trino_table_locator(table: Table, context: HogQLContext) -> TrinoTableLocator | None:
    if isinstance(table, DirectTrinoTable):
        locator = (table.trino_catalog, table.trino_schema, table.trino_table_name)
        for label, value in zip(("catalog name", "schema name", "table name"), locator):
            if not value.strip():
                raise QueryError(f"Direct Trino tables require a {label}.")
        return locator
    return context.trino_table_locators.get(_logical_name(table))


def missing_trino_locator_error_code(table: Table) -> str:
    if isinstance(table, PostgresTable):
        return "TRINO_APP_DATABASE_TABLE_UNSUPPORTED"
    if not isinstance(table, FunctionCallTable) and _logical_name(table) not in _EXPORTED_POSTHOG_TABLE_SCANS:
        return "TRINO_CLICKHOUSE_ONLY_TABLE_UNSUPPORTED"
    return "TRINO_TABLE_LOCATOR_MISSING"


def _logical_name(table: Table) -> str:
    return getattr(table, "trino_locator_name", None) or table.name or table.to_printed_hogql()
