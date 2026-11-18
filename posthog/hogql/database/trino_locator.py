from __future__ import annotations

from typing import TYPE_CHECKING

from posthog.hogql.database.direct_trino_table import DirectTrinoTable
from posthog.hogql.errors import QueryError

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.database.models import Table


TrinoTableLocator = tuple[str, str, str]


def resolve_trino_table_locator(table: Table, context: HogQLContext) -> TrinoTableLocator | None:
    if isinstance(table, DirectTrinoTable):
        locator = (table.trino_catalog, table.trino_schema, table.trino_table_name)
        for label, value in zip(("catalog name", "schema name", "table name"), locator):
            if not value.strip():
                raise QueryError(f"Direct Trino tables require a {label}.")
        return locator
    logical_name = getattr(table, "trino_locator_name", None) or table.name or table.to_printed_hogql()
    return context.trino_table_locators.get(logical_name)
