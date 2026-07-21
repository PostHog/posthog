from dataclasses import dataclass
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

    usages: dict[str, WarehouseSourceUsage] = {}
    for table_type in extract_base_table_types(select_type):
        table = table_type.table
        if not isinstance(table, (S3Table, DirectPostgresTable)):
            continue
        source_id = getattr(table, "external_data_source_id", None)
        if not source_id or source_id in usages:
            continue
        usages[source_id] = WarehouseSourceUsage(
            id=source_id,
            source_type=getattr(table, "source_type", None),
            table_name=getattr(table, "name", "") or "",
        )
    return list(usages.values())
