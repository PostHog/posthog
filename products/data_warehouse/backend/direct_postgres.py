from typing import Any

from products.data_warehouse.backend.models import DataWarehouseTable
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.util import postgres_column_to_dwh_column

DIRECT_POSTGRES_URL_PATTERN = "direct://postgres"

type DirectPostgresColumns = dict[str, dict[str, str | bool]]


def postgres_schema_metadata_to_dwh_columns(schema_metadata: dict[str, Any] | None) -> DirectPostgresColumns:
    resolved_columns: DirectPostgresColumns = {}
    if not schema_metadata:
        return resolved_columns

    columns = schema_metadata.get("columns")
    if not isinstance(columns, list):
        return resolved_columns

    for column in columns:
        if not isinstance(column, dict):
            continue

        column_name = column.get("name")
        postgres_type = column.get("data_type")
        nullable = bool(column.get("is_nullable"))

        if not isinstance(column_name, str) or not isinstance(postgres_type, str):
            continue

        resolved_columns[column_name] = postgres_column_to_dwh_column(column_name, postgres_type, nullable)

    return resolved_columns


def upsert_direct_postgres_table(
    existing_table: DataWarehouseTable | None,
    *,
    schema_name: str,
    source: ExternalDataSource,
    columns: DirectPostgresColumns,
) -> DataWarehouseTable:
    if existing_table is None:
        return DataWarehouseTable.objects.create(
            name=schema_name,
            format=DataWarehouseTable.TableFormat.Parquet,
            team_id=source.team_id,
            url_pattern=DIRECT_POSTGRES_URL_PATTERN,
            external_data_source=source,
            columns=columns,
        )

    existing_table.name = schema_name
    existing_table.url_pattern = DIRECT_POSTGRES_URL_PATTERN
    existing_table.external_data_source = source
    existing_table.columns = columns
    existing_table.deleted = False
    existing_table.deleted_at = None
    existing_table.save(
        update_fields=[
            "name",
            "url_pattern",
            "external_data_source",
            "columns",
            "deleted",
            "deleted_at",
            "updated_at",
        ]
    )
    return existing_table


def hide_direct_postgres_table(table: DataWarehouseTable | None) -> None:
    if table is not None and not table.deleted:
        table.soft_delete()
