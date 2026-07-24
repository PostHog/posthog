"""Direct-query Postgres helpers — manages the live-query `DataWarehouseTable` that lets HogQL hit
Postgres without going through Delta. Code shared with warehouse mode lives in `postgres_helpers.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from products.warehouse_sources.backend.facade.models import ExternalDataSource

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.table import DataWarehouseTable

type DirectPostgresColumns = dict[str, dict[str, Any]]

DIRECT_POSTGRES_URL_PATTERN = "direct://postgres"
DIRECT_POSTGRES_CATALOG_OPTION = "direct_postgres_catalog"
DIRECT_POSTGRES_SCHEMA_OPTION = "direct_postgres_schema"
DIRECT_POSTGRES_TABLE_OPTION = "direct_postgres_table"


def get_direct_postgres_table_options(
    *, source_catalog: str | None = None, source_schema: str, source_table_name: str
) -> dict[str, str]:
    options = {
        DIRECT_POSTGRES_SCHEMA_OPTION: source_schema,
        DIRECT_POSTGRES_TABLE_OPTION: source_table_name,
    }
    if source_catalog:
        options[DIRECT_POSTGRES_CATALOG_OPTION] = source_catalog
    return options


def upsert_direct_postgres_table(
    existing_table: DataWarehouseTable | None,
    *,
    schema_name: str,
    source: ExternalDataSource,
    columns: DirectPostgresColumns,
    source_catalog: str | None = None,
    source_schema: str,
    source_table_name: str,
) -> DataWarehouseTable:
    from products.warehouse_sources.backend.facade.models import DataWarehouseTable

    options = {
        **(existing_table.options if existing_table is not None and isinstance(existing_table.options, dict) else {}),
        **get_direct_postgres_table_options(
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
            url_pattern=DIRECT_POSTGRES_URL_PATTERN,
            external_data_source=source,
            columns=columns,
            options=options,
        )

    existing_table.name = schema_name
    existing_table.url_pattern = DIRECT_POSTGRES_URL_PATTERN
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


def hide_direct_postgres_table(table: DataWarehouseTable | None) -> None:
    if table is not None and not table.deleted:
        table.soft_delete()


def rename_direct_postgres_join_references(*, team_id: int, old_name: str, new_name: str) -> None:
    if old_name == new_name:
        return
    from products.data_tools.backend.models.join import DataWarehouseJoin

    DataWarehouseJoin.objects.filter(team_id=team_id, source_table_name=old_name).update(source_table_name=new_name)
    DataWarehouseJoin.objects.filter(team_id=team_id, joining_table_name=old_name).update(joining_table_name=new_name)
