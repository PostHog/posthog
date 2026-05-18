"""Migrate pre-PR Postgres warehouse rows to qualified naming without re-syncing.

Legacy rows are renamed in place (`example_table` → `public.example_table`) and tagged with
`dwh_storage_key=<original_name>` so `pipeline_sync` and `source_for_pipeline` keep writing/reading
at the legacy Delta path — no S3 rewrite, no orphaned data.

Triggered from PATCH (schema cleared) and refresh_schemas (idempotent reconcile).
"""

from __future__ import annotations

from typing import Any

from posthog.temporal.data_imports.sources.common.schema import SourceSchema

from products.data_warehouse.backend.direct_postgres import (
    _normalize_default_schema,
    rename_direct_postgres_schemas_to_match_source_schemas,
)
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource


def _qualify_legacy_row(
    row: Any,
    *,
    target_source_schema: str,
    target_source_table_name: str | None = None,
    duplicate_to_drop: Any | None = None,
) -> str | None:
    """Rename `row` from unqualified to qualified form, stash `dwh_storage_key`, optionally drop a
    duplicate qualified row.

    Returns the new qualified name on success, or None if consolidation had to be skipped because
    the duplicate already owns data (UNIQUE name collision risk).
    """
    sync_type_config = row.sync_type_config or {}
    existing_metadata_raw = sync_type_config.get("schema_metadata")
    existing_metadata: dict[str, Any] = dict(existing_metadata_raw) if isinstance(existing_metadata_raw, dict) else {}

    effective_source_schema = existing_metadata.get("source_schema") or target_source_schema
    effective_source_table_name = existing_metadata.get("source_table_name") or target_source_table_name or row.name
    qualified_name = f"{effective_source_schema}.{effective_source_table_name}"

    # Refuse to overwrite a duplicate that already has its own DataWarehouseTable — destroying real
    # data is worse than living with two rows the user can resolve manually via the UI.
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
    # Lock the Delta storage path to the original unqualified key so existing files stay readable.
    if "dwh_storage_key" not in sync_type_config:
        new_sync_type_config["dwh_storage_key"] = row.name

    row.name = qualified_name
    row.sync_type_config = new_sync_type_config
    row.save(update_fields=["name", "sync_type_config", "updated_at"])
    return qualified_name


def apply_on_schema_clear(source: ExternalDataSource, old_schema: str) -> None:
    """Triggered by PATCH when the user clears `job_inputs.schema`.

    Without this hook the next refresh sees `default_schema=None`, falls back to `"public"`, and
    points legacy rows at the wrong physical table.
    """
    from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

    rows = list(ExternalDataSchema.objects.filter(team_id=source.team_id, source_id=source.id, deleted=False))
    rows_by_name = {row.name: row for row in rows}

    for row in rows:
        if "." in row.name:
            continue
        # Compute the qualified target the same way `_qualify_legacy_row` will, so we can find any
        # pre-existing duplicate row that needs soft-deleting before the rename.
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
    source_type: str,
    existing_job_inputs: dict[str, Any],
    incoming_job_inputs: dict[str, Any],
) -> str | None:
    """Return the old default schema if this PATCH is clearing a previously-set Postgres
    `job_inputs.schema`, otherwise None.
    """
    if source_type != "Postgres":
        return None
    if "schema" not in incoming_job_inputs:
        return None
    incoming = incoming_job_inputs.get("schema")
    if isinstance(incoming, str) and incoming.strip():
        return None
    existing = existing_job_inputs.get("schema")
    if not (isinstance(existing, str) and existing.strip()):
        return None
    return existing.strip()


def _extract_source_location_from_row(row: Any) -> tuple[str | None, str | None]:
    """`(source_schema, source_table_name)` for an ExternalDataSchema row — metadata first, dotted
    name as fallback. Returns `(None, None)` for unqualified rows with no metadata.
    """
    metadata = (row.sync_type_config or {}).get("schema_metadata")
    source_schema: str | None = None
    source_table_name: str | None = None
    if isinstance(metadata, dict):
        if isinstance(metadata.get("source_schema"), str):
            source_schema = metadata["source_schema"]
        if isinstance(metadata.get("source_table_name"), str):
            source_table_name = metadata["source_table_name"]
    if (not source_schema or not source_table_name) and "." in row.name:
        inferred_schema, _, inferred_table = row.name.partition(".")
        source_schema = source_schema or inferred_schema or None
        source_table_name = source_table_name or inferred_table or None
    return source_schema, source_table_name


def reconcile_refresh_name_substitutions(
    *,
    source: ExternalDataSource,
    source_schemas: list[SourceSchema],
    team_id: int,
) -> dict[str, str]:
    """Compute the full set of name substitutions for a Postgres refresh.

    Combines the rename helper (matches discovered names to existing rows by location) with the
    consolidate helper (drops legacy/qualified duplicates, qualifies legacy in place) and chains
    them so callers feed a single dict into `sync_old_schemas_with_new_schemas`.
    """
    name_substitutions = rename_direct_postgres_schemas_to_match_source_schemas(
        source=source,
        source_schemas=source_schemas,
        team_id=team_id,
        # Renaming a warehouse-mode row would change its Delta path on the next sync. Only direct
        # mode (which has always eager-renamed) opts in here; warehouse mode goes through
        # `apply_on_refresh` below, which preserves the Delta path via `dwh_storage_key`.
        allow_rename=source.is_direct_query,
    )

    if not source.is_direct_query:
        consolidation_substitutions = apply_on_refresh(source=source, team_id=team_id)
        # Chain: rename helper said {discovered_X: existing_Y}; if consolidate just renamed Y → Z,
        # the discovered name now resolves to Z.
        for old_name, new_name in consolidation_substitutions.items():
            for discovered, existing in list(name_substitutions.items()):
                if existing == old_name:
                    name_substitutions[discovered] = new_name
        name_substitutions = {**name_substitutions, **consolidation_substitutions}
        name_substitutions = {k: v for k, v in name_substitutions.items() if k != v}

    return name_substitutions


def apply_on_refresh(*, source: ExternalDataSource, team_id: int) -> dict[str, str]:
    """Triggered by `refresh_schemas`. Idempotent — runs every refresh, no-ops once everything is
    qualified.

    Matches legacy rows to qualified duplicates by `source_table_name` (not full location) because
    a legacy row's location falls back to `"public"` when `job_inputs.schema` is blank, while the
    discovered row points at e.g. `"poblic"` — cross-pairing on table name is the only signal that
    survives that gap.

    Returns `{old_name: new_name}` for any renamed/soft-deleted rows. Callers feed this into the
    schema_names dict before `sync_old_schemas_with_new_schemas` so the legacy row is recognized
    as already covering its discovered qualified equivalent.
    """
    from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

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

    default_schema = _normalize_default_schema((source.job_inputs or {}).get("schema"))
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
