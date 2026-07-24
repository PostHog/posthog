"""ClickHouse source helpers shared between warehouse and direct-query modes.

Direct-query-only utilities (DataWarehouseTable upserts, the `direct://clickhouse` url_pattern, the
option keys that encode source location on a direct table) live in `direct_clickhouse.py`. ClickHouse
namespaces a table as database.table — there is no separate catalog level, and no foreign keys.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db.models import Q

import structlog

from products.data_warehouse.backend.direct_clickhouse import (
    DIRECT_CLICKHOUSE_DATABASE_OPTION,
    DIRECT_CLICKHOUSE_TABLE_OPTION,
    hide_direct_clickhouse_table,
    upsert_direct_clickhouse_table,
)
from products.warehouse_sources.backend.facade.models import (
    ExternalDataSource,
    clickhouse_column_to_dwh_column,
    clickhouse_columns_to_dwh_columns,
)
from products.warehouse_sources.backend.facade.source_management import (
    SourceSchema,
    extract_available_column_names,
    filter_columns_by_enabled_columns,
    filter_dwh_columns_by_enabled_columns,
    normalize_namespace,
    prune_enabled_columns,
    sql_schema_metadata,
)

if TYPE_CHECKING:
    pass

log = structlog.get_logger(__name__)

type ClickHouseDwhColumns = dict[str, dict[str, Any]]
# (database, table). ClickHouse has no separate catalog level.
type ClickHouseSourceLocation = tuple[str, str]

# ClickHouse's implicit default database when a source config leaves it unset.
_DEFAULT_CLICKHOUSE_DATABASE = "default"


def clickhouse_schema_metadata_to_dwh_columns(schema_metadata: dict[str, Any] | None) -> ClickHouseDwhColumns:
    resolved: ClickHouseDwhColumns = {}
    if not schema_metadata:
        return resolved
    columns = schema_metadata.get("columns")
    if not isinstance(columns, list):
        return resolved
    for column in columns:
        if not isinstance(column, dict):
            continue
        column_name = column.get("name")
        clickhouse_type = column.get("data_type")
        nullable = bool(column.get("is_nullable"))
        if not isinstance(column_name, str) or not isinstance(clickhouse_type, str):
            continue
        resolved[column_name] = clickhouse_column_to_dwh_column(column_name, clickhouse_type, nullable)
    return resolved


def get_clickhouse_source_location(
    *,
    schema_name: str,
    schema_metadata: dict[str, Any] | None = None,
    default_database: str | None = None,
) -> ClickHouseSourceLocation:
    """Resolve `(source_database, source_table_name)` for a ClickHouse row.

    Priority: explicit metadata → dot-split when no default database → default database fallback.
    """
    source_schema = schema_metadata.get("source_schema") if isinstance(schema_metadata, dict) else None
    source_table_name = schema_metadata.get("source_table_name") if isinstance(schema_metadata, dict) else None
    normalized_default = normalize_namespace(default_database)

    if isinstance(source_schema, str) and isinstance(source_table_name, str):
        return source_schema, source_table_name

    if normalized_default is None and "." in schema_name:
        inferred_database, inferred_table = schema_name.split(".", 1)
        return inferred_database, inferred_table

    return normalized_default or _DEFAULT_CLICKHOUSE_DATABASE, schema_name


def get_clickhouse_source_location_for_schema_model(
    *,
    schema_name: str,
    sync_type_config: dict[str, Any] | None = None,
    table_options: dict[str, Any] | None = None,
    default_database: str | None = None,
) -> ClickHouseSourceLocation:
    schema_metadata = (
        sync_type_config.get("schema_metadata")
        if isinstance(sync_type_config, dict) and isinstance(sync_type_config.get("schema_metadata"), dict)
        else None
    )
    if schema_metadata is not None:
        return get_clickhouse_source_location(
            schema_name=schema_name, schema_metadata=schema_metadata, default_database=default_database
        )

    table_source_database = (
        table_options.get(DIRECT_CLICKHOUSE_DATABASE_OPTION) if isinstance(table_options, dict) else None
    )
    table_source_table_name = (
        table_options.get(DIRECT_CLICKHOUSE_TABLE_OPTION) if isinstance(table_options, dict) else None
    )
    if isinstance(table_source_database, str) and isinstance(table_source_table_name, str):
        return table_source_database, table_source_table_name

    if "." in schema_name:
        inferred_database, inferred_table = schema_name.split(".", 1)
        return inferred_database, inferred_table

    return get_clickhouse_source_location(
        schema_name=schema_name, schema_metadata=None, default_database=default_database
    )


def reconcile_clickhouse_schemas(
    *,
    source: ExternalDataSource,
    source_schemas: list[SourceSchema],
    team_id: int,
) -> list[str]:
    """Persist `schema_metadata` on every ClickHouse row + (direct mode only) upsert its live-query
    `DataWarehouseTable`. Returns stale schema names that got soft-deleted (direct only)."""
    from products.warehouse_sources.backend.facade.models import ExternalDataSchema

    is_direct = source.is_direct_query
    source_schema_names = [s.name for s in source_schemas]
    default_database = (source.job_inputs or {}).get("database")
    schema_models = {
        s.name: s
        for s in ExternalDataSchema.objects.filter(team_id=team_id, source_id=source.id, deleted=False).select_related(
            "table"
        )
    }

    schema_models_by_location: dict[ClickHouseSourceLocation, ExternalDataSchema] = {}
    for schema_model in schema_models.values():
        location = get_clickhouse_source_location_for_schema_model(
            schema_name=schema_model.name,
            sync_type_config=schema_model.sync_type_config,
            table_options=schema_model.table.options if schema_model.table is not None else None,
            default_database=default_database,
        )
        schema_models_by_location.setdefault(location, schema_model)

    for source_schema in source_schemas:
        matched: ExternalDataSchema | None = schema_models.get(source_schema.name)
        if matched is None:
            location = get_clickhouse_source_location(
                schema_name=source_schema.name,
                schema_metadata={
                    "source_schema": source_schema.source_schema,
                    "source_table_name": source_schema.source_table_name,
                },
                default_database=default_database,
            )
            matched = schema_models_by_location.get(location)
        if matched is None:
            continue

        resolved_database, resolved_table = get_clickhouse_source_location(
            schema_name=source_schema.name,
            schema_metadata={
                "source_schema": source_schema.source_schema,
                "source_table_name": source_schema.source_table_name,
            },
            default_database=default_database,
        )
        # Metadata holds the full column list (column-picker UI); projection lives on `enabled_columns`.
        schema_metadata = sql_schema_metadata(
            source_schema.columns,
            [],
            source_catalog=None,
            source_schema=resolved_database,
            source_table_name=resolved_table,
        )
        new_sync_type_config = {**(matched.sync_type_config or {}), "schema_metadata": schema_metadata}
        if source_schema.detected_primary_keys and not new_sync_type_config.get("primary_key_columns"):
            new_sync_type_config["primary_key_columns"] = source_schema.detected_primary_keys
        matched.sync_type_config = new_sync_type_config
        update_fields = ["sync_type_config", "updated_at"]

        available_names = extract_available_column_names(schema_metadata)
        pruned_enabled_columns, removed_columns = prune_enabled_columns(matched.enabled_columns, available_names)
        if removed_columns:
            log.info(
                "clickhouse.reconcile_schemas.pruned_enabled_columns",
                source_id=str(source.id),
                schema_id=str(matched.id),
                schema_name=matched.name,
                removed_columns=removed_columns,
            )
            matched.enabled_columns = pruned_enabled_columns
            update_fields.append("enabled_columns")
        matched.save(update_fields=update_fields)

        if not is_direct:
            continue

        if not matched.should_sync:
            hide_direct_clickhouse_table(matched.table)
            continue

        projected_columns = filter_columns_by_enabled_columns(
            source_schema.columns,
            matched.enabled_columns,
            source_schema.detected_primary_keys,
            matched.incremental_field,
        )
        table_model = upsert_direct_clickhouse_table(
            matched.table,
            schema_name=source_schema.name,
            source=source,
            columns=clickhouse_columns_to_dwh_columns(projected_columns),
            source_database=resolved_database,
            source_table_name=resolved_table,
        )
        if matched.table_id != table_model.id:
            matched.table = table_model
            matched.save(update_fields=["table"])

    if not is_direct:
        return []

    stale_names: list[str] = []
    stale = ExternalDataSchema.objects.filter(
        Q(team_id=team_id, source_id=source.id),
        Q(deleted=False) | Q(table__deleted=False),
    ).exclude(name__in=source_schema_names)
    for s in stale:
        hide_direct_clickhouse_table(s.table)
        if not s.deleted:
            s.soft_delete()
        stale_names.append(s.name)
    return stale_names


def reproject_direct_clickhouse_table(
    schema_row: Any,
    *,
    source: ExternalDataSource,
    enabled_columns: list[str] | None,
) -> Any:
    """Rebuild the direct-query `DataWarehouseTable` with a fresh column projection — used on
    column-picker save and on `should_sync` False → True. No re-sync needed in direct mode."""
    source_database, source_table_name = get_clickhouse_source_location(
        schema_name=schema_row.name,
        schema_metadata=schema_row.schema_metadata,
        default_database=(source.job_inputs or {}).get("database"),
    )
    return upsert_direct_clickhouse_table(
        schema_row.table,
        schema_name=schema_row.name,
        source=source,
        columns=filter_dwh_columns_by_enabled_columns(
            clickhouse_schema_metadata_to_dwh_columns(schema_row.schema_metadata),
            enabled_columns,
            schema_row.primary_key_columns,
            schema_row.incremental_field,
            # Direct-ClickHouse columns are keyed by raw, case-sensitive source names.
            normalize=False,
        ),
        source_database=source_database,
        source_table_name=source_table_name,
    )
