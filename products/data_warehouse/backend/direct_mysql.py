"""Direct-query MySQL helpers — manages the live-query `DataWarehouseTable` that lets HogQL hit
MySQL without going through Delta. Code shared with warehouse mode lives in `mysql_helpers.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.table import DataWarehouseTable

type DirectMySQLColumns = dict[str, dict[str, Any]]

DIRECT_MYSQL_URL_PATTERN = "direct://mysql"
DIRECT_MYSQL_SCHEMA_OPTION = "direct_mysql_schema"
DIRECT_MYSQL_TABLE_OPTION = "direct_mysql_table"


def get_direct_mysql_table_options(*, source_schema: str, source_table_name: str) -> dict[str, str]:
    return {
        DIRECT_MYSQL_SCHEMA_OPTION: source_schema,
        DIRECT_MYSQL_TABLE_OPTION: source_table_name,
    }


def upsert_direct_mysql_table(
    existing_table: DataWarehouseTable | None,
    *,
    schema_name: str,
    source: ExternalDataSource,
    columns: DirectMySQLColumns,
    source_schema: str,
    source_table_name: str,
) -> DataWarehouseTable:
    from products.warehouse_sources.backend.models.table import DataWarehouseTable

    options = {
        **(existing_table.options if existing_table is not None and isinstance(existing_table.options, dict) else {}),
        **get_direct_mysql_table_options(
            source_schema=source_schema,
            source_table_name=source_table_name,
        ),
    }

    if existing_table is None:
        return DataWarehouseTable.objects.create(
            name=schema_name,
            format=DataWarehouseTable.TableFormat.Parquet,
            team_id=source.team_id,
            url_pattern=DIRECT_MYSQL_URL_PATTERN,
            external_data_source=source,
            columns=columns,
            options=options,
        )

    existing_table.name = schema_name
    existing_table.url_pattern = DIRECT_MYSQL_URL_PATTERN
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


def hide_direct_mysql_table(table: DataWarehouseTable | None) -> None:
    if table is not None and not table.deleted:
        table.soft_delete()
