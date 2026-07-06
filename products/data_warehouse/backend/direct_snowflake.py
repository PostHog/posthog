from __future__ import annotations

from typing import TYPE_CHECKING, Any

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.table import DataWarehouseTable

type DirectSnowflakeColumns = dict[str, dict[str, Any]]


DIRECT_SNOWFLAKE_URL_PATTERN = "direct://snowflake"
DIRECT_SNOWFLAKE_CATALOG_OPTION = "direct_snowflake_catalog"
DIRECT_SNOWFLAKE_SCHEMA_OPTION = "direct_snowflake_schema"
DIRECT_SNOWFLAKE_TABLE_OPTION = "direct_snowflake_table"


def get_direct_snowflake_table_options(
    *, source_catalog: str | None = None, source_schema: str, source_table_name: str
) -> dict[str, str]:
    options = {
        DIRECT_SNOWFLAKE_SCHEMA_OPTION: source_schema,
        DIRECT_SNOWFLAKE_TABLE_OPTION: source_table_name,
    }
    if source_catalog:
        options[DIRECT_SNOWFLAKE_CATALOG_OPTION] = source_catalog
    return options


def upsert_direct_snowflake_table(
    existing_table: DataWarehouseTable | None,
    *,
    schema_name: str,
    source: ExternalDataSource,
    columns: DirectSnowflakeColumns,
    source_catalog: str | None = None,
    source_schema: str,
    source_table_name: str,
) -> DataWarehouseTable:
    from products.warehouse_sources.backend.models.table import DataWarehouseTable

    options = {
        **(existing_table.options if existing_table is not None and isinstance(existing_table.options, dict) else {}),
        **get_direct_snowflake_table_options(
            source_catalog=source_catalog,
            source_schema=source_schema,
            source_table_name=source_table_name,
        ),
    }

    if existing_table is None:
        return DataWarehouseTable.objects.create(
            name=schema_name,
            format=DataWarehouseTable.TableFormat.Parquet,
            team_id=source.team_id,
            url_pattern=DIRECT_SNOWFLAKE_URL_PATTERN,
            external_data_source=source,
            columns=columns,
            options=options,
        )

    existing_table.name = schema_name
    existing_table.url_pattern = DIRECT_SNOWFLAKE_URL_PATTERN
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


def hide_direct_snowflake_table(table: DataWarehouseTable | None) -> None:
    if table is not None and not table.deleted:
        table.soft_delete()
