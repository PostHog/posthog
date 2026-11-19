from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Optional

from posthog.hogql import ast
from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.resolver_utils import extract_base_table_types


@dataclass(frozen=True)
class WarehouseSourceUsage:
    """A connector-synced data warehouse source referenced by a query."""

    id: str
    source_type: Optional[str]
    table_name: str
    uses_history_table: bool = False


def extract_warehouse_sources(
    select_type: "ast.SelectQueryType | ast.SelectSetQueryType | None",
) -> list[WarehouseSourceUsage]:
    """Return the connector-synced data warehouse sources referenced by a *resolved* query.

    Only tables backed by an ``ExternalDataSource`` are included — self-managed S3 tables have no
    ``external_data_source_id`` and are excluded, as are native tables (events/persons/sessions) and
    coincidentally-named CTEs/subqueries (resolution distinguishes these from real tables).
    Deduplicated by source id, preserving first-seen order.
    """
    if select_type is None:
        return []

    usages: list[WarehouseSourceUsage] = []
    for table_type in extract_base_table_types(select_type):
        table = table_type.table
        if not isinstance(table, (S3Table, DirectPostgresTable)):
            continue
        source_id = getattr(table, "external_data_source_id", None)
        if not source_id:
            continue
        usages.append(
            WarehouseSourceUsage(
                id=source_id,
                source_type=getattr(table, "source_type", None),
                table_name=getattr(table, "name", "") or "",
                uses_history_table=getattr(table, "is_history_table", False),
            )
        )
    return merge_warehouse_sources(usages)


def merge_warehouse_sources(usages: Iterable[WarehouseSourceUsage]) -> list[WarehouseSourceUsage]:
    """One entry per source, first-seen order. The source counts as history usage if any read was."""
    merged: dict[str, WarehouseSourceUsage] = {}
    for usage in usages:
        existing = merged.get(usage.id)
        if existing is None:
            merged[usage.id] = usage
        elif usage.uses_history_table and not existing.uses_history_table:
            merged[usage.id] = replace(existing, uses_history_table=True)
    return list(merged.values())
