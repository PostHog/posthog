"""Direct-query ClickHouse helpers — manages the live-query `DataWarehouseTable` that lets HogQL hit
an external ClickHouse without going through Delta. Code shared with warehouse mode lives in
`clickhouse_helpers.py`. ClickHouse namespaces a table as database.table (no separate catalog level).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from products.warehouse_sources.backend.facade.models import ExternalDataSource

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.table import DataWarehouseTable

type DirectClickHouseColumns = dict[str, dict[str, Any]]

DIRECT_CLICKHOUSE_URL_PATTERN = "direct://clickhouse"
DIRECT_CLICKHOUSE_DATABASE_OPTION = "direct_clickhouse_database"
DIRECT_CLICKHOUSE_TABLE_OPTION = "direct_clickhouse_table"


def get_direct_clickhouse_table_options(*, source_database: str, source_table_name: str) -> dict[str, str]:
    return {
        DIRECT_CLICKHOUSE_DATABASE_OPTION: source_database,
        DIRECT_CLICKHOUSE_TABLE_OPTION: source_table_name,
    }


def upsert_direct_clickhouse_table(
    existing_table: DataWarehouseTable | None,
    *,
    schema_name: str,
    source: ExternalDataSource,
    columns: DirectClickHouseColumns,
    source_database: str,
    source_table_name: str,
) -> DataWarehouseTable:
    from products.warehouse_sources.backend.facade.models import DataWarehouseTable

    options = {
        **(existing_table.options if existing_table is not None and isinstance(existing_table.options, dict) else {}),
        **get_direct_clickhouse_table_options(source_database=source_database, source_table_name=source_table_name),
    }

    if existing_table is None:
        return DataWarehouseTable.objects.create(
            name=schema_name,
            format=DataWarehouseTable.TableFormat.Parquet,
            team_id=source.team_id,
            url_pattern=DIRECT_CLICKHOUSE_URL_PATTERN,
            external_data_source=source,
            columns=columns,
            options=options,
        )

    existing_table.name = schema_name
    existing_table.url_pattern = DIRECT_CLICKHOUSE_URL_PATTERN
    existing_table.external_data_source = source
    existing_table.columns = columns
    existing_table.options = options
    existing_table.deleted = False
    existing_table.deleted_at = None
    existing_table.save(
        update_fields=[
            "name",
            "url_pattern",
            "external_data_source",
            "columns",
            "options",
            "deleted",
            "deleted_at",
            "updated_at",
        ]
    )
    return existing_table


def hide_direct_clickhouse_table(table: DataWarehouseTable | None) -> None:
    if table is not None and not table.deleted:
        table.soft_delete()
