"""Postgres source helpers shared between warehouse and direct-query modes.

Direct-query-mode-only utilities (DataWarehouseTable upserts, the `direct://postgres` url_pattern,
the option keys that encode source location on a direct table) live in `direct_postgres.py`. This
module holds the parts both modes need: schema metadata builders, location resolution, column
filtering, and the reconcile/rename helpers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from django.db.models import Q

from posthog.temporal.data_imports.sources.common.schema import SourceSchema

from products.data_warehouse.backend.direct_postgres import (
    DIRECT_POSTGRES_CATALOG_OPTION,
    DIRECT_POSTGRES_SCHEMA_OPTION,
    DIRECT_POSTGRES_TABLE_OPTION,
    hide_direct_postgres_table,
    rename_direct_postgres_join_references,
    upsert_direct_postgres_table,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.util import (
    postgres_column_to_dwh_column,
    postgres_columns_to_dwh_columns,
)

if TYPE_CHECKING:
    pass

_TColumnValue = TypeVar("_TColumnValue")

type PostgresDwhColumns = dict[str, dict[str, Any]]
type PostgresSourceLocation = tuple[str | None, str, str]


def _normalize_default_schema(default_schema: str | None) -> str | None:
    if not isinstance(default_schema, str):
        return None
    normalized = default_schema.strip()
    return normalized or None


def postgres_schema_metadata(
    columns: list[tuple[str, str, bool]],
    foreign_keys: list[tuple[str, str, str]] | None = None,
    source_catalog: str | None = None,
    source_schema: str | None = None,
    source_table_name: str | None = None,
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
        "source_catalog": source_catalog,
        "source_schema": source_schema,
        "source_table_name": source_table_name,
    }


def postgres_schema_metadata_to_dwh_columns(schema_metadata: dict[str, Any] | None) -> PostgresDwhColumns:
    resolved: PostgresDwhColumns = {}
    if not schema_metadata:
        return resolved
    columns = schema_metadata.get("columns")
    if not isinstance(columns, list):
        return resolved
    for column in columns:
        if not isinstance(column, dict):
            continue
        column_name = column.get("name")
        postgres_type = column.get("data_type")
        nullable = bool(column.get("is_nullable"))
        if not isinstance(column_name, str) or not isinstance(postgres_type, str):
            continue
        resolved[column_name] = postgres_column_to_dwh_column(column_name, postgres_type, nullable)
    return resolved


def get_postgres_source_location(
    *,
    schema_name: str,
    schema_metadata: dict[str, Any] | None = None,
    default_schema: str | None = None,
) -> PostgresSourceLocation:
    """Resolve `(source_catalog, source_schema, source_table_name)` for a Postgres row.

    Priority: explicit metadata → dot-split when no default schema → default schema fallback.
    """
    source_catalog = schema_metadata.get("source_catalog") if isinstance(schema_metadata, dict) else None
    source_schema = schema_metadata.get("source_schema") if isinstance(schema_metadata, dict) else None
    source_table_name = schema_metadata.get("source_table_name") if isinstance(schema_metadata, dict) else None
    normalized_default = _normalize_default_schema(default_schema)

    if isinstance(source_schema, str) and isinstance(source_table_name, str):
        return source_catalog if isinstance(source_catalog, str) else None, source_schema, source_table_name

    if normalized_default is None and "." in schema_name:
        inferred_schema, inferred_table = schema_name.split(".", 1)
        return None, inferred_schema, inferred_table

    return None, normalized_default or "public", schema_name


def get_postgres_source_location_for_schema_model(
    *,
    schema_name: str,
    sync_type_config: dict[str, Any] | None = None,
    table_options: dict[str, Any] | None = None,
    default_schema: str | None = None,
) -> PostgresSourceLocation:
    schema_metadata = (
        sync_type_config.get("schema_metadata")
        if isinstance(sync_type_config, dict) and isinstance(sync_type_config.get("schema_metadata"), dict)
        else None
    )
    if schema_metadata is not None:
        return get_postgres_source_location(
            schema_name=schema_name,
            schema_metadata=schema_metadata,
            default_schema=default_schema,
        )

    table_source_schema = table_options.get(DIRECT_POSTGRES_SCHEMA_OPTION) if isinstance(table_options, dict) else None
    table_source_table_name = (
        table_options.get(DIRECT_POSTGRES_TABLE_OPTION) if isinstance(table_options, dict) else None
    )
    table_source_catalog = (
        table_options.get(DIRECT_POSTGRES_CATALOG_OPTION) if isinstance(table_options, dict) else None
    )
    if isinstance(table_source_schema, str) and isinstance(table_source_table_name, str):
        return (
            table_source_catalog if isinstance(table_source_catalog, str) else None,
            table_source_schema,
            table_source_table_name,
        )

    # Legacy direct-query rows may only have the schema encoded in the display name.
    if "." in schema_name:
        inferred_schema, inferred_table = schema_name.split(".", 1)
        return None, inferred_schema, inferred_table

    return get_postgres_source_location(
        schema_name=schema_name,
        schema_metadata=None,
        default_schema=default_schema,
    )


def filter_dwh_columns_by_enabled_columns(
    columns: dict[str, _TColumnValue],
    enabled_columns: list[str] | None,
    primary_keys: list[str] | None,
    incremental_field: str | None = None,
) -> dict[str, _TColumnValue]:
    # `None` and `[]` are distinct: `None` syncs all, `[]` retains only PKs + incremental.
    if enabled_columns is None:
        return columns
    retained: set[str] = set(enabled_columns)
    for pk in primary_keys or []:
        retained.add(pk)
    if incremental_field:
        retained.add(incremental_field)
    return {name: column for name, column in columns.items() if name in retained}


def filter_columns_by_enabled_columns(
    columns: list[tuple[str, str, bool]],
    enabled_columns: list[str] | None,
    primary_keys: list[str] | None,
    incremental_field: str | None = None,
) -> list[tuple[str, str, bool]]:
    if enabled_columns is None:
        return columns
    retained: set[str] = set(enabled_columns)
    for pk in primary_keys or []:
        retained.add(pk)
    if incremental_field:
        retained.add(incremental_field)
    return [col for col in columns if col[0] in retained]


def reconcile_postgres_schemas(
    *,
    source: ExternalDataSource,
    source_schemas: list[SourceSchema],
    team_id: int,
) -> list[str]:
    """Persist `schema_metadata` on every Postgres row + (direct mode only) upsert its live-query
    `DataWarehouseTable`. Returns stale schema names that got soft-deleted (direct only)."""
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

    is_direct = source.is_direct_query
    source_schema_names = [s.name for s in source_schemas]
    default_schema = (source.job_inputs or {}).get("schema")
    schema_models = {
        s.name: s for s in ExternalDataSchema.objects.filter(team_id=team_id, source_id=source.id, deleted=False)
    }

    # Location-indexed fallback so unqualified legacy rows still resolve to their qualified
    # discovered counterparts on every refresh.
    schema_models_by_location: dict[PostgresSourceLocation, ExternalDataSchema] = {}
    for schema_model in schema_models.values():
        location = get_postgres_source_location_for_schema_model(
            schema_name=schema_model.name,
            sync_type_config=schema_model.sync_type_config,
            table_options=schema_model.table.options if schema_model.table is not None else None,
            default_schema=default_schema,
        )
        schema_models_by_location.setdefault(location, schema_model)

    for source_schema in source_schemas:
        matched: ExternalDataSchema | None = schema_models.get(source_schema.name)
        if matched is None:
            location = get_postgres_source_location(
                schema_name=source_schema.name,
                schema_metadata={
                    "source_catalog": source_schema.source_catalog,
                    "source_schema": source_schema.source_schema,
                    "source_table_name": source_schema.source_table_name,
                },
                default_schema=default_schema,
            )
            matched = schema_models_by_location.get(location)
        if matched is None:
            continue

        resolved_catalog, resolved_schema, resolved_table = get_postgres_source_location(
            schema_name=source_schema.name,
            schema_metadata={
                "source_catalog": source_schema.source_catalog,
                "source_schema": source_schema.source_schema,
                "source_table_name": source_schema.source_table_name,
            },
            default_schema=default_schema,
        )
        # Metadata holds the full column list (column-picker UI); projection lives on `enabled_columns`.
        schema_metadata = postgres_schema_metadata(
            source_schema.columns,
            source_schema.foreign_keys,
            source_catalog=resolved_catalog,
            source_schema=resolved_schema,
            source_table_name=resolved_table,
        )
        matched.sync_type_config = {**(matched.sync_type_config or {}), "schema_metadata": schema_metadata}
        matched.save(update_fields=["sync_type_config", "updated_at"])

        if not is_direct:
            # Warehouse mode: the ingestion workflow manages `DataWarehouseTable` itself.
            continue

        if not matched.should_sync:
            hide_direct_postgres_table(matched.table)
            continue

        projected_columns = filter_columns_by_enabled_columns(
            source_schema.columns,
            matched.enabled_columns,
            source_schema.detected_primary_keys,
            matched.incremental_field,
        )
        table_model = upsert_direct_postgres_table(
            matched.table,
            schema_name=source_schema.name,
            source=source,
            columns=postgres_columns_to_dwh_columns(projected_columns),
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
    stale = ExternalDataSchema.objects.filter(
        Q(team_id=team_id, source_id=source.id),
        Q(deleted=False) | Q(table__deleted=False),
    ).exclude(name__in=source_schema_names)
    for s in stale:
        hide_direct_postgres_table(s.table)
        if not s.deleted:
            s.soft_delete()
        stale_names.append(s.name)
    return stale_names


def reproject_direct_postgres_table(
    schema_row: Any,
    *,
    source: ExternalDataSource,
    enabled_columns: list[str] | None,
) -> Any:
    """Rebuild the direct-query `DataWarehouseTable` with a fresh column projection — used on
    column-picker save and on `should_sync` False → True. No re-sync needed in direct mode.
    """
    source_catalog, source_schema, source_table_name = get_postgres_source_location(
        schema_name=schema_row.name,
        schema_metadata=schema_row.schema_metadata,
        default_schema=(source.job_inputs or {}).get("schema"),
    )
    return upsert_direct_postgres_table(
        schema_row.table,
        schema_name=schema_row.name,
        source=source,
        columns=filter_dwh_columns_by_enabled_columns(
            postgres_schema_metadata_to_dwh_columns(schema_row.schema_metadata),
            enabled_columns,
            schema_row.primary_key_columns,
            schema_row.incremental_field,
        ),
        source_catalog=source_catalog,
        source_schema=source_schema,
        source_table_name=source_table_name,
    )


def rename_postgres_schemas_to_match_source_schemas(
    *,
    source: ExternalDataSource,
    source_schemas: list[SourceSchema],
    team_id: int,
    allow_rename: bool = True,
) -> dict[str, str]:
    """Match discovered schemas to existing rows by source location.
    Direct mode (`allow_rename=True`) rewrites `name` in place; warehouse mode pins
    `schema_metadata` only — the rename happens in `postgres_warehouse_migration`.
    """
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

    default_schema = (source.job_inputs or {}).get("schema")
    schema_models = list(
        ExternalDataSchema.objects.filter(team_id=team_id, source_id=source.id, deleted=False).select_related("table")
    )
    schema_models_by_name = {s.name: s for s in schema_models}
    schema_models_by_location: dict[PostgresSourceLocation, list[ExternalDataSchema]] = {}
    for s in schema_models:
        location = get_postgres_source_location_for_schema_model(
            schema_name=s.name,
            sync_type_config=s.sync_type_config,
            table_options=s.table.options if s.table is not None else None,
            default_schema=default_schema,
        )
        schema_models_by_location.setdefault(location, []).append(s)

    renamed_ids: set[str] = set()
    name_substitutions: dict[str, str] = {}

    for source_schema in source_schemas:
        if source_schema.name in schema_models_by_name:
            continue
        location = get_postgres_source_location(
            schema_name=source_schema.name,
            schema_metadata={
                "source_catalog": source_schema.source_catalog,
                "source_schema": source_schema.source_schema,
                "source_table_name": source_schema.source_table_name,
            },
            default_schema=default_schema,
        )
        candidate = next(
            (
                s
                for s in schema_models_by_location.get(location, [])
                if str(s.id) not in renamed_ids and s.name != source_schema.name
            ),
            None,
        )
        if candidate is None:
            continue

        if not allow_rename:
            # Pin metadata so reconcile matches `candidate` to this discovered table by location.
            sync_type_config = candidate.sync_type_config or {}
            existing_metadata = sync_type_config.get("schema_metadata")
            if not isinstance(existing_metadata, dict) or not existing_metadata.get("source_table_name"):
                candidate.sync_type_config = {
                    **sync_type_config,
                    "schema_metadata": postgres_schema_metadata(
                        source_schema.columns,
                        source_schema.foreign_keys,
                        source_catalog=source_schema.source_catalog,
                        source_schema=source_schema.source_schema,
                        source_table_name=source_schema.source_table_name,
                    ),
                }
                candidate.save(update_fields=["sync_type_config", "updated_at"])
            name_substitutions[source_schema.name] = candidate.name
            schema_models_by_name[source_schema.name] = candidate
            renamed_ids.add(str(candidate.id))
            continue

        old_name = candidate.name
        candidate.name = source_schema.name
        candidate.save(update_fields=["name", "updated_at"])
        rename_direct_postgres_join_references(team_id=team_id, old_name=old_name, new_name=source_schema.name)
        schema_models_by_name.pop(old_name, None)
        schema_models_by_name[source_schema.name] = candidate
        renamed_ids.add(str(candidate.id))

    return name_substitutions
