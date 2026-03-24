from typing import Any

from django.db.models import Q

from posthog.temporal.data_imports.sources.common.schema import SourceSchema

from products.data_warehouse.backend.models import DataWarehouseTable, ExternalDataSchema
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.util import postgres_column_to_dwh_column, postgres_columns_to_dwh_columns

DIRECT_POSTGRES_URL_PATTERN = "direct://postgres"

type DirectPostgresColumns = dict[str, dict[str, Any]]


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


def postgres_schema_metadata(
    columns: list[tuple[str, str, bool]], foreign_keys: list[tuple[str, str, str]] | None = None
) -> dict[str, Any]:
    return {
        "columns": [
            {"name": column_name, "data_type": postgres_type, "is_nullable": nullable}
            for column_name, postgres_type, nullable in columns
        ],
        "foreign_keys": [
            {"column": column_name, "target_table": target_table, "target_column": target_column}
            for column_name, target_table, target_column in (foreign_keys or [])
        ],
    }


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


def reconcile_direct_postgres_schemas(
    *,
    source: ExternalDataSource,
    source_schemas: list[SourceSchema],
    team_id: int,
) -> list[str]:
    source_schema_names = [schema.name for schema in source_schemas]
    schema_models = {
        schema.name: schema
        for schema in ExternalDataSchema.objects.filter(team_id=team_id, source_id=source.id, deleted=False)
    }

    for source_schema in source_schemas:
        schema_model = schema_models.get(source_schema.name)
        if schema_model is None:
            continue

        schema_metadata = postgres_schema_metadata(source_schema.columns, source_schema.foreign_keys)
        schema_model.sync_type_config = {**(schema_model.sync_type_config or {}), "schema_metadata": schema_metadata}
        schema_model.save(update_fields=["sync_type_config", "updated_at"])

        if not schema_model.should_sync:
            hide_direct_postgres_table(schema_model.table)
            continue

        table_model = upsert_direct_postgres_table(
            schema_model.table,
            schema_name=source_schema.name,
            source=source,
            columns=postgres_columns_to_dwh_columns(source_schema.columns),
        )
        if schema_model.table_id != table_model.id:
            schema_model.table = table_model
            schema_model.save(update_fields=["table"])

    stale_schema_names: list[str] = []
    stale_schemas = ExternalDataSchema.objects.filter(
        Q(team_id=team_id, source_id=source.id),
        Q(deleted=False) | Q(table__deleted=False),
    ).exclude(name__in=source_schema_names)

    for stale_schema in stale_schemas:
        hide_direct_postgres_table(stale_schema.table)
        if not stale_schema.deleted:
            stale_schema.soft_delete()
        stale_schema_names.append(stale_schema.name)

    return stale_schema_names
