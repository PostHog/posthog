from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.database.models import Table


TrinoTableLocator = tuple[str, str, str]


def resolve_trino_table_locator(table: Table, context: HogQLContext) -> TrinoTableLocator | None:
    logical_name = table.name or table.to_printed_hogql()
    return context.trino_table_locators.get(logical_name)
