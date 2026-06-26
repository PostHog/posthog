"""Migrate pre-multi-schema SQL warehouse rows to qualified naming without re-syncing.

Legacy rows are renamed in place (`users` → `public.users`) and tagged `s3_folder_name=<original>`
so sync keeps reading/writing the legacy Delta path. Source-agnostic — gated only by the namespace
field being blank-able; Postgres direct-query plumbing stays in `postgres_warehouse_migration.py`.
"""

from __future__ import annotations

from typing import Any

from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import SQLSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.location import (
    fill_missing_from_dotted_name,
    normalize_namespace,
)


def _source_has_optional_schema_field(source: Any) -> bool:
    """True when `source` is a SQL source whose `schema` namespace field is optional (blank-able)."""
    if not isinstance(source, SQLSource):
        return False
    try:
        fields = source.get_source_config.fields
    except (AttributeError, TypeError):
        return False
    return any(
        getattr(field, "name", None) == "schema" and getattr(field, "required", True) is False for field in fields
    )


def is_multi_schema_capable_sql_source(source_type: ExternalDataSourceType | str) -> bool:
    """True when the registered source for `source_type` has an optional (blank-able) `schema` field.

    The optional field is the opt-in marker (Postgres, MSSQL, Snowflake, Redshift today). Resolved via
    `get_all_sources`, not the test-mockable `get_source`, so the gate stays config-driven.
    """
    try:
        resolved_type = ExternalDataSourceType(source_type)
    except ValueError:
        return False
    return _source_has_optional_schema_field(SourceRegistry.get_all_sources().get(resolved_type))


def source_namespace_is_blank(source: ExternalDataSource) -> bool:
    """True when the source's `job_inputs.schema` is unset — i.e. it's in multi-schema mode."""
    schema = (source.job_inputs or {}).get("schema")
    return not (isinstance(schema, str) and schema.strip())


def _qualify_legacy_row(
    row: Any,
    *,
    target_source_schema: str,
    target_source_table_name: str | None = None,
    duplicate_to_drop: Any | None = None,
) -> str | None:
    """Rename `row` to qualified form, stash `s3_folder_name`, optionally drop a duplicate.
    Returns the new name, or None if a duplicate with its own data blocked the rename.
    """
    sync_type_config = row.sync_type_config or {}
    existing_metadata_raw = sync_type_config.get("schema_metadata")
    existing_metadata: dict[str, Any] = dict(existing_metadata_raw) if isinstance(existing_metadata_raw, dict) else {}

    effective_source_schema = existing_metadata.get("source_schema") or target_source_schema
    effective_source_table_name = existing_metadata.get("source_table_name") or target_source_table_name or row.name
    qualified_name = f"{effective_source_schema}.{effective_source_table_name}"

    # Don't soft-delete a duplicate that already owns synced data; let the user resolve manually.
    if duplicate_to_drop is not None and duplicate_to_drop.id != row.id:
        if duplicate_to_drop.table_id is not None:
            return None
        duplicate_to_drop.soft_delete()

    merged_metadata: dict[str, Any] = dict(existing_metadata)
    merged_metadata.setdefault("source_catalog", existing_metadata.get("source_catalog"))
    merged_metadata["source_schema"] = effective_source_schema
    merged_metadata["source_table_name"] = effective_source_table_name
    merged_metadata.setdefault("columns", [])
    merged_metadata.setdefault("foreign_keys", [])

    new_sync_type_config: dict[str, Any] = {**sync_type_config, "schema_metadata": merged_metadata}

    update_fields = ["name", "sync_type_config", "updated_at"]
    if not row.s3_folder_name:
        # The S3 folder is the normalized identifier — store that, so the column holds the real
        # folder name (matching what the backfill writes and what readers compute). `resolved_*`
        # picks up any legacy `dwh_storage_key` so a previously-migrated row keeps its path.
        row.s3_folder_name = NamingConvention.normalize_identifier(row.resolved_s3_folder_name or row.name)
        update_fields.append("s3_folder_name")

    row.name = qualified_name
    row.sync_type_config = new_sync_type_config
    row.save(update_fields=update_fields)
    return qualified_name


def apply_on_schema_clear(source: ExternalDataSource, old_schema: str) -> None:
    """Pin legacy rows to the OLD schema before the next refresh sees `default_schema=None` and
    misroutes them to `"public"`.
    """
    from products.warehouse_sources.backend.facade.models import ExternalDataSchema

    rows = list(ExternalDataSchema.objects.filter(team_id=source.team_id, source_id=source.id, deleted=False))
    rows_by_name = {row.name: row for row in rows}

    for row in rows:
        if "." in row.name:
            continue
        existing_metadata = (row.sync_type_config or {}).get("schema_metadata") or {}
        effective_schema = existing_metadata.get("source_schema") if isinstance(existing_metadata, dict) else None
        effective_table = existing_metadata.get("source_table_name") if isinstance(existing_metadata, dict) else None
        qualified_name = f"{effective_schema or old_schema}.{effective_table or row.name}"
        _qualify_legacy_row(
            row,
            target_source_schema=old_schema,
            duplicate_to_drop=rows_by_name.get(qualified_name),
        )


def detect_schema_clear_transition(
    *,
    source_type: ExternalDataSourceType | str,
    existing_job_inputs: dict[str, Any],
    incoming_job_inputs: dict[str, Any],
) -> str | None:
    """Return the old schema if this PATCH clears a multi-schema SQL source's `job_inputs.schema`."""
    if "schema" not in incoming_job_inputs:
        return None
    incoming = incoming_job_inputs.get("schema")
    if isinstance(incoming, str) and incoming.strip():
        return None
    existing = existing_job_inputs.get("schema")
    if not (isinstance(existing, str) and existing.strip()):
        return None
    # Cheap dict/string checks first; only pay the registry/config capability lookup on a real clear.
    if not is_multi_schema_capable_sql_source(source_type):
        return None
    return existing.strip()


def _extract_source_location_from_row(row: Any) -> tuple[str | None, str | None]:
    """`(source_schema, source_table_name)` — metadata first, dotted name fallback, else `(None, None)`."""
    metadata = (row.sync_type_config or {}).get("schema_metadata")
    source_schema: str | None = None
    source_table_name: str | None = None
    if isinstance(metadata, dict):
        if isinstance(metadata.get("source_schema"), str):
            source_schema = metadata["source_schema"]
        if isinstance(metadata.get("source_table_name"), str):
            source_table_name = metadata["source_table_name"]
    return fill_missing_from_dotted_name(source_schema, source_table_name, row.name)


def apply_on_refresh(*, source: ExternalDataSource, team_id: int) -> dict[str, str]:
    """Idempotent reconcile — qualifies legacy rows, drops refresh-created duplicates.

    Matches legacy → qualified by `source_table_name` (not full location) because a legacy row
    falls back to `"public"` when `job_inputs.schema` is blank, missing the actual schema.
    Returns `{old_name: new_name}` for callers feeding `sync_old_schemas_with_new_schemas`.
    """
    from products.warehouse_sources.backend.facade.models import ExternalDataSchema

    rows = list(
        ExternalDataSchema.objects.filter(team_id=team_id, source_id=source.id, deleted=False).select_related("table")
    )

    qualified_rows_by_table_name: dict[str, list[tuple[str, ExternalDataSchema]]] = {}
    unqualified_rows: list[ExternalDataSchema] = []
    for row in rows:
        if "." in row.name:
            source_schema, source_table_name = _extract_source_location_from_row(row)
            if source_schema and source_table_name:
                qualified_rows_by_table_name.setdefault(source_table_name, []).append((source_schema, row))
        else:
            unqualified_rows.append(row)

    default_schema = normalize_namespace((source.job_inputs or {}).get("schema"))
    name_substitutions: dict[str, str] = {}

    for legacy in unqualified_rows:
        legacy_metadata_source_schema, legacy_metadata_source_table_name = _extract_source_location_from_row(legacy)
        qualified_matches = qualified_rows_by_table_name.get(legacy.name, [])

        # Disambiguate multi-match using legacy's own pinned metadata.
        if len(qualified_matches) > 1 and legacy_metadata_source_schema is not None:
            filtered = [m for m in qualified_matches if m[0] == legacy_metadata_source_schema]
            if len(filtered) == 1:
                qualified_matches = filtered

        target_source_schema: str | None
        target_source_table_name: str | None = legacy_metadata_source_table_name
        duplicate: Any | None = None

        if len(qualified_matches) == 1:
            target_source_schema, duplicate = qualified_matches[0]
        elif len(qualified_matches) > 1:
            # Ambiguous — let the user resolve via the UI.
            continue
        elif legacy_metadata_source_schema is not None:
            target_source_schema = legacy_metadata_source_schema
        elif default_schema is not None:
            target_source_schema = default_schema
        else:
            continue

        original_name = legacy.name
        new_name = _qualify_legacy_row(
            legacy,
            target_source_schema=target_source_schema,
            target_source_table_name=target_source_table_name,
            duplicate_to_drop=duplicate,
        )
        if new_name is None:
            continue
        if duplicate is not None and duplicate.id != legacy.id:
            name_substitutions[duplicate.name] = new_name
        name_substitutions[original_name] = new_name

    return name_substitutions
