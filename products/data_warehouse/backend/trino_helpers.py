"""Trino source helpers shared between warehouse and direct-query modes.

Direct-query-only utilities (DataWarehouseTable upserts, the `direct://trino`
url_pattern, the option keys that encode source location on a direct table) live in
`direct_trino.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from products.data_warehouse.backend.direct_trino import (
    DIRECT_TRINO_CATALOG_OPTION,
    DIRECT_TRINO_SCHEMA_OPTION,
    DIRECT_TRINO_TABLE_OPTION,
    hide_direct_trino_table,
    upsert_direct_trino_table,
)
from products.warehouse_sources.backend.facade.models import (
    ExternalDataSource,
    get_schemas_for_direct_reconciliation,
    trino_column_to_dwh_column,
    trino_columns_to_dwh_columns,
)
from products.warehouse_sources.backend.facade.source_management import (
    SourceSchema,
    extract_available_column_names,
    filter_dwh_columns_by_enabled_columns,
    normalize_namespace,
    prune_enabled_columns,
    sql_schema_metadata,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

log = structlog.get_logger(__name__)

type TrinoSourceLocation = tuple[str | None, str, str]  # (database, schema, table_name)


def get_default_trino_catalog(source: ExternalDataSource) -> str | None:
    catalog = (source.job_inputs or {}).get("catalog")
    return catalog if isinstance(catalog, str) and catalog.strip() else None


def trino_schema_metadata_to_dwh_columns(schema_metadata: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    if not schema_metadata:
        return resolved
    columns = schema_metadata.get("columns")
    if not isinstance(columns, list):
        return resolved
    for column in columns:
        if not isinstance(column, dict):
            continue
        column_name = column.get("name")
        trino_type = column.get("data_type")
        nullable = bool(column.get("is_nullable"))
        if not isinstance(column_name, str) or not isinstance(trino_type, str):
            continue
        resolved[column_name] = trino_column_to_dwh_column(column_name, trino_type, nullable)
    return resolved


def reproject_direct_trino_table(
    schema_row: Any,
    *,
    source: ExternalDataSource,
    enabled_columns: list[str] | None,
) -> Any:
    """Rebuild the direct-query `DataWarehouseTable` with a fresh column projection — used on
    column-picker save and on `should_sync` False → True. No re-sync needed in direct mode."""
    source_catalog, source_schema, source_table_name = get_trino_source_location(
        schema_name=schema_row.name,
        schema_metadata=schema_row.schema_metadata,
        default_catalog=get_default_trino_catalog(source),
    )
    return upsert_direct_trino_table(
        schema_row.table,
        schema_name=schema_row.name,
        source=source,
        columns=filter_dwh_columns_by_enabled_columns(
            trino_schema_metadata_to_dwh_columns(schema_row.schema_metadata),
            enabled_columns,
            schema_row.primary_key_columns,
            schema_row.incremental_field,
            # Direct-Trino columns are keyed by raw, case-sensitive source names.
            normalize=False,
        ),
        source_catalog=source_catalog,
        source_schema=source_schema,
        source_table_name=source_table_name,
    )


def get_trino_source_location(
    *,
    schema_name: str,
    schema_metadata: dict[str, Any] | None = None,
    default_catalog: str | None = None,
    default_schema: str | None = None,
) -> TrinoSourceLocation:
    """Resolve (database, schema, table_name) for a Trino source.

    Discovery always stamps the full location into `schema_metadata`; name parsing exists
    only for rows created without it (`db.schema.table` or `schema.table` display names).
    """
    source_catalog = schema_metadata.get("source_catalog") if isinstance(schema_metadata, dict) else None
    source_schema = schema_metadata.get("source_schema") if isinstance(schema_metadata, dict) else None
    source_table_name = schema_metadata.get("source_table_name") if isinstance(schema_metadata, dict) else None
    normalized_default_schema = normalize_namespace(default_schema)

    catalog = source_catalog if isinstance(source_catalog, str) and source_catalog.strip() else default_catalog
    if isinstance(source_schema, str) and isinstance(source_table_name, str):
        return catalog, source_schema, source_table_name

    parts = schema_name.split(".")
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return catalog, parts[0], parts[1]

    return catalog, normalized_default_schema or "", schema_name


def get_trino_source_location_for_schema_model(
    *,
    schema_name: str,
    sync_type_config: dict[str, Any] | None = None,
    table_options: dict[str, Any] | None = None,
    default_catalog: str | None = None,
) -> TrinoSourceLocation:
    schema_metadata = (
        sync_type_config.get("schema_metadata")
        if isinstance(sync_type_config, dict) and isinstance(sync_type_config.get("schema_metadata"), dict)
        else None
    )
    if schema_metadata is not None:
        return get_trino_source_location(
            schema_name=schema_name,
            schema_metadata=schema_metadata,
            default_catalog=default_catalog,
        )

    opts = table_options if isinstance(table_options, dict) else {}
    table_source_catalog = opts.get(DIRECT_TRINO_CATALOG_OPTION)
    table_source_schema = opts.get(DIRECT_TRINO_SCHEMA_OPTION)
    table_source_table_name = opts.get(DIRECT_TRINO_TABLE_OPTION)

    if isinstance(table_source_schema, str) and isinstance(table_source_table_name, str):
        return (
            table_source_catalog if isinstance(table_source_catalog, str) else default_catalog,
            table_source_schema,
            table_source_table_name,
        )

    return get_trino_source_location(
        schema_name=schema_name,
        schema_metadata=None,
        default_catalog=default_catalog,
    )


def reconcile_trino_schemas(
    *,
    source: ExternalDataSource,
    source_schemas: list[SourceSchema],
    team_id: int,
) -> list[str]:
    """Persist `schema_metadata` on every Trino row + (direct mode only) upsert its
    live-query `DataWarehouseTable`. Returns stale schema names that got soft-deleted (direct
    only)."""

    is_direct = source.is_direct_query
    source_schema_names = [s.name for s in source_schemas]
    default_catalog = get_default_trino_catalog(source)
    reconciliation = get_schemas_for_direct_reconciliation(
        source_id=source.id,
        team_id=team_id,
        current_schema_names=source_schema_names,
    )
    schema_models = {schema.name: schema for schema in reconciliation.active_schemas}

    schema_models_by_location: dict[TrinoSourceLocation, ExternalDataSchema] = {}
    for schema_model in schema_models.values():
        location = get_trino_source_location_for_schema_model(
            schema_name=schema_model.name,
            sync_type_config=schema_model.sync_type_config,
            table_options=schema_model.table.options if schema_model.table is not None else None,
            default_catalog=default_catalog,
        )
        schema_models_by_location.setdefault(location, schema_model)

    for source_schema in source_schemas:
        resolved = get_trino_source_location(
            schema_name=source_schema.name,
            schema_metadata={
                "source_catalog": source_schema.source_catalog,
                "source_schema": source_schema.source_schema,
                "source_table_name": source_schema.source_table_name,
            },
            default_catalog=default_catalog,
        )
        matched: ExternalDataSchema | None = schema_models.get(source_schema.name)
        if matched is None:
            matched = schema_models_by_location.get(resolved)
        if matched is None:
            continue

        resolved_catalog, resolved_schema, resolved_table = resolved

        # Metadata holds the full column list (column-picker UI); projection lives on `enabled_columns`.
        schema_metadata = sql_schema_metadata(
            source_schema.columns,
            source_schema.foreign_keys,
            source_catalog=resolved_catalog,
            source_schema=resolved_schema,
            source_table_name=resolved_table,
        )
        new_sync_type_config = {**(matched.sync_type_config or {}), "schema_metadata": schema_metadata}
        # Persist the detected primary key without clobbering a value already stored — e.g. an
        # explicit override set during creation or a prior refresh.
        if source_schema.detected_primary_keys and not new_sync_type_config.get("primary_key_columns"):
            new_sync_type_config["primary_key_columns"] = source_schema.detected_primary_keys
        matched.sync_type_config = new_sync_type_config
        update_fields = ["sync_type_config", "updated_at"]

        # Drop dead columns so the next projection doesn't reference `missing_col`.
        available_names = extract_available_column_names(schema_metadata)
        pruned_enabled_columns, removed_columns = prune_enabled_columns(matched.enabled_columns, available_names)
        if removed_columns:
            log.info(
                "trino.reconcile_schemas.pruned_enabled_columns",
                source_id=str(source.id),
                schema_id=str(matched.id),
                schema_name=matched.name,
                removed_columns=removed_columns,
            )
            matched.enabled_columns = pruned_enabled_columns
            update_fields.append("enabled_columns")
        matched.save(update_fields=update_fields)

        if not is_direct:
            # Warehouse mode: the ingestion workflow manages `DataWarehouseTable` itself.
            continue

        if not matched.should_sync:
            hide_direct_trino_table(matched.table)
            continue

        projected_columns = filter_dwh_columns_by_enabled_columns(
            trino_columns_to_dwh_columns(source_schema.columns),
            matched.enabled_columns,
            source_schema.detected_primary_keys,
            matched.incremental_field,
            # Direct-Trino columns are keyed by raw, case-sensitive source names. The
            # guarded helper falls back to all columns when a projection would empty out,
            # so a stale selection can't leave the live table unqueryable.
            normalize=False,
        )
        table_model = upsert_direct_trino_table(
            matched.table,
            schema_name=source_schema.name,
            source=source,
            columns=projected_columns,
            source_catalog=resolved_catalog,
            source_schema=resolved_schema,
            source_table_name=resolved_table,
        )
        if matched.table_id != table_model.id:
            matched.table = table_model
            matched.save(update_fields=["table"])

    if not is_direct:
        # Warehouse mode delegates add/delete to `sync_old_schemas_with_new_schemas`.
        return []

    stale_names: list[str] = []
    for s in reconciliation.stale_schemas:
        hide_direct_trino_table(s.table)
        if not s.deleted:
            s.soft_delete()
        stale_names.append(s.name)
    return stale_names
