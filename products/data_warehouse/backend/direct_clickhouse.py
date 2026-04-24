from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db.models import Q

from posthog.temporal.data_imports.sources.common.schema import SourceSchema

from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.util import CLICKHOUSE_TYPE_TO_HOGQL_LABEL, clean_type

if TYPE_CHECKING:
    from products.data_warehouse.backend.models import ExternalDataSchema
    from products.data_warehouse.backend.models.table import DataWarehouseTable

DIRECT_CLICKHOUSE_URL_PATTERN = "direct://clickhouse"
DIRECT_CLICKHOUSE_DATABASE_OPTION = "direct_clickhouse_database"
DIRECT_CLICKHOUSE_TABLE_OPTION = "direct_clickhouse_table"

type DirectClickHouseColumns = dict[str, dict[str, Any]]
type DirectClickHouseLocation = tuple[str, str]


def _normalize_default_database(default_database: str | None) -> str:
    if isinstance(default_database, str) and default_database.strip():
        return default_database.strip()
    return "default"


def clickhouse_column_to_dwh_column(clickhouse_type: str, nullable: bool) -> dict[str, Any]:
    persisted_type = clickhouse_type
    if nullable and not persisted_type.startswith("Nullable("):
        persisted_type = f"Nullable({persisted_type})"

    raw_clickhouse_type = clean_type(persisted_type)
    hogql_type = CLICKHOUSE_TYPE_TO_HOGQL_LABEL.get(raw_clickhouse_type, "string")
    if raw_clickhouse_type.startswith("DateTime"):
        hogql_type = "datetime"
    elif raw_clickhouse_type.startswith("Decimal"):
        hogql_type = "numeric"
    elif raw_clickhouse_type.startswith("Array"):
        hogql_type = "array"
    elif raw_clickhouse_type.startswith("Map") or raw_clickhouse_type.startswith("Tuple"):
        hogql_type = "json"

    return {
        "clickhouse": persisted_type,
        "hogql": hogql_type,
        "valid": True,
    }


def clickhouse_columns_to_dwh_columns(columns: list[tuple[str, str, bool]]) -> DirectClickHouseColumns:
    return {
        column_name: clickhouse_column_to_dwh_column(clickhouse_type, nullable)
        for column_name, clickhouse_type, nullable in columns
    }


def clickhouse_schema_metadata_to_dwh_columns(schema_metadata: dict[str, Any] | None) -> DirectClickHouseColumns:
    resolved_columns: DirectClickHouseColumns = {}
    if not schema_metadata:
        return resolved_columns

    columns = schema_metadata.get("columns")
    if not isinstance(columns, list):
        return resolved_columns

    for column in columns:
        if not isinstance(column, dict):
            continue

        column_name = column.get("name")
        clickhouse_type = column.get("data_type")
        nullable = bool(column.get("is_nullable"))

        if not isinstance(column_name, str) or not isinstance(clickhouse_type, str):
            continue

        resolved_columns[column_name] = clickhouse_column_to_dwh_column(clickhouse_type, nullable)

    return resolved_columns


def clickhouse_schema_metadata(
    columns: list[tuple[str, str, bool]],
    *,
    source_database: str | None = None,
    source_table_name: str | None = None,
) -> dict[str, Any]:
    return {
        "columns": [
            {"name": column_name, "data_type": clickhouse_type, "is_nullable": nullable}
            for column_name, clickhouse_type, nullable in columns
        ],
        "source_database": source_database,
        "source_table_name": source_table_name,
    }


def get_direct_clickhouse_location(
    *,
    schema_name: str,
    schema_metadata: dict[str, Any] | None = None,
    default_database: str | None = None,
) -> DirectClickHouseLocation:
    source_database = schema_metadata.get("source_database") if isinstance(schema_metadata, dict) else None
    source_table_name = schema_metadata.get("source_table_name") if isinstance(schema_metadata, dict) else None

    if isinstance(source_database, str) and isinstance(source_table_name, str):
        return source_database, source_table_name

    return _normalize_default_database(default_database), schema_name


def get_direct_clickhouse_location_for_schema_model(
    *,
    schema_name: str,
    sync_type_config: dict[str, Any] | None = None,
    table_options: dict[str, Any] | None = None,
    default_database: str | None = None,
) -> DirectClickHouseLocation:
    schema_metadata = (
        sync_type_config.get("schema_metadata")
        if isinstance(sync_type_config, dict) and isinstance(sync_type_config.get("schema_metadata"), dict)
        else None
    )

    if schema_metadata is not None:
        return get_direct_clickhouse_location(
            schema_name=schema_name,
            schema_metadata=schema_metadata,
            default_database=default_database,
        )

    table_source_database = (
        table_options.get(DIRECT_CLICKHOUSE_DATABASE_OPTION) if isinstance(table_options, dict) else None
    )
    table_source_table_name = (
        table_options.get(DIRECT_CLICKHOUSE_TABLE_OPTION) if isinstance(table_options, dict) else None
    )

    if isinstance(table_source_database, str) and isinstance(table_source_table_name, str):
        return table_source_database, table_source_table_name

    return get_direct_clickhouse_location(
        schema_name=schema_name,
        schema_metadata=None,
        default_database=default_database,
    )


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
    from products.data_warehouse.backend.models.table import DataWarehouseTable

    options = {
        **(existing_table.options if existing_table is not None and isinstance(existing_table.options, dict) else {}),
        **get_direct_clickhouse_table_options(
            source_database=source_database,
            source_table_name=source_table_name,
        ),
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


def rename_direct_clickhouse_join_references(*, team_id: int, old_name: str, new_name: str) -> None:
    if old_name == new_name:
        return

    from products.data_warehouse.backend.models.join import DataWarehouseJoin

    DataWarehouseJoin.objects.filter(team_id=team_id, source_table_name=old_name).update(source_table_name=new_name)
    DataWarehouseJoin.objects.filter(team_id=team_id, joining_table_name=old_name).update(joining_table_name=new_name)


def reconcile_direct_clickhouse_schemas(
    *,
    source: ExternalDataSource,
    source_schemas: list[SourceSchema],
    team_id: int,
) -> list[str]:
    from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

    source_schema_names = [schema.name for schema in source_schemas]
    schema_models = {
        schema.name: schema
        for schema in ExternalDataSchema.objects.filter(team_id=team_id, source_id=source.id, deleted=False)
    }

    for source_schema in source_schemas:
        schema_model = schema_models.get(source_schema.name)
        if schema_model is None:
            continue

        resolved_source_database, resolved_source_table_name = get_direct_clickhouse_location(
            schema_name=source_schema.name,
            schema_metadata={
                "source_database": source_schema.source_schema,
                "source_table_name": source_schema.source_table_name,
            },
            default_database=(source.job_inputs or {}).get("database"),
        )
        schema_metadata = clickhouse_schema_metadata(
            source_schema.columns,
            source_database=resolved_source_database,
            source_table_name=resolved_source_table_name,
        )
        schema_model.sync_type_config = {**(schema_model.sync_type_config or {}), "schema_metadata": schema_metadata}
        schema_model.save(update_fields=["sync_type_config", "updated_at"])

        if not schema_model.should_sync:
            hide_direct_clickhouse_table(schema_model.table)
            continue

        table_model = upsert_direct_clickhouse_table(
            schema_model.table,
            schema_name=source_schema.name,
            source=source,
            columns=clickhouse_columns_to_dwh_columns(source_schema.columns),
            source_database=resolved_source_database,
            source_table_name=resolved_source_table_name,
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
        hide_direct_clickhouse_table(stale_schema.table)
        if not stale_schema.deleted:
            stale_schema.soft_delete()
        stale_schema_names.append(stale_schema.name)

    return stale_schema_names


def rename_direct_clickhouse_schemas_to_match_source_schemas(
    *,
    source: ExternalDataSource,
    source_schemas: list[SourceSchema],
    team_id: int,
) -> None:
    from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

    default_database = (source.job_inputs or {}).get("database")
    schema_models = list(
        ExternalDataSchema.objects.filter(team_id=team_id, source_id=source.id, deleted=False).select_related("table")
    )
    schema_models_by_name = {schema.name: schema for schema in schema_models}
    schema_models_by_location: dict[DirectClickHouseLocation, list[ExternalDataSchema]] = {}

    for schema_model in schema_models:
        location = get_direct_clickhouse_location_for_schema_model(
            schema_name=schema_model.name,
            sync_type_config=schema_model.sync_type_config,
            table_options=schema_model.table.options if schema_model.table is not None else None,
            default_database=default_database,
        )
        schema_models_by_location.setdefault(location, []).append(schema_model)

    renamed_schema_ids: set[str] = set()

    for source_schema in source_schemas:
        if source_schema.name in schema_models_by_name:
            continue

        location = get_direct_clickhouse_location(
            schema_name=source_schema.name,
            schema_metadata={
                "source_database": source_schema.source_schema,
                "source_table_name": source_schema.source_table_name,
            },
            default_database=default_database,
        )
        rename_candidate = next(
            (
                schema_model
                for schema_model in schema_models_by_location.get(location, [])
                if str(schema_model.id) not in renamed_schema_ids and schema_model.name != source_schema.name
            ),
            None,
        )
        if rename_candidate is None:
            continue

        old_name = rename_candidate.name
        rename_candidate.name = source_schema.name
        rename_candidate.save(update_fields=["name", "updated_at"])
        rename_direct_clickhouse_join_references(team_id=team_id, old_name=old_name, new_name=source_schema.name)
        schema_models_by_name.pop(old_name, None)
        schema_models_by_name[source_schema.name] = rename_candidate
        renamed_schema_ids.add(str(rename_candidate.id))
