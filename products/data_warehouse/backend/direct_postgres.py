from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from django.db.models import Q

from posthog.temporal.data_imports.sources.common.schema import SourceSchema

from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.util import postgres_column_to_dwh_column, postgres_columns_to_dwh_columns

if TYPE_CHECKING:
    from products.data_warehouse.backend.models.table import DataWarehouseTable

_TColumnValue = TypeVar("_TColumnValue")

DIRECT_POSTGRES_URL_PATTERN = "direct://postgres"
DIRECT_POSTGRES_CATALOG_OPTION = "direct_postgres_catalog"
DIRECT_POSTGRES_SCHEMA_OPTION = "direct_postgres_schema"
DIRECT_POSTGRES_TABLE_OPTION = "direct_postgres_table"

type DirectPostgresColumns = dict[str, dict[str, Any]]
type DirectPostgresLocation = tuple[str | None, str, str]


def _normalize_default_schema(default_schema: str | None) -> str | None:
    if not isinstance(default_schema, str):
        return None

    normalized_default_schema = default_schema.strip()
    return normalized_default_schema or None


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


def get_direct_postgres_location(
    *,
    schema_name: str,
    schema_metadata: dict[str, Any] | None = None,
    default_schema: str | None = None,
) -> tuple[str | None, str, str]:
    source_catalog = schema_metadata.get("source_catalog") if isinstance(schema_metadata, dict) else None
    source_schema = schema_metadata.get("source_schema") if isinstance(schema_metadata, dict) else None
    source_table_name = schema_metadata.get("source_table_name") if isinstance(schema_metadata, dict) else None
    normalized_default_schema = _normalize_default_schema(default_schema)

    if isinstance(source_schema, str) and isinstance(source_table_name, str):
        return source_catalog if isinstance(source_catalog, str) else None, source_schema, source_table_name

    if normalized_default_schema is None and "." in schema_name:
        inferred_schema, inferred_table_name = schema_name.split(".", 1)
        return None, inferred_schema, inferred_table_name

    return None, normalized_default_schema or "public", schema_name


def get_direct_postgres_location_for_schema_model(
    *,
    schema_name: str,
    sync_type_config: dict[str, Any] | None = None,
    table_options: dict[str, Any] | None = None,
    default_schema: str | None = None,
) -> DirectPostgresLocation:
    schema_metadata = (
        sync_type_config.get("schema_metadata")
        if isinstance(sync_type_config, dict) and isinstance(sync_type_config.get("schema_metadata"), dict)
        else None
    )

    if schema_metadata is not None:
        return get_direct_postgres_location(
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
        inferred_schema, inferred_table_name = schema_name.split(".", 1)
        return None, inferred_schema, inferred_table_name

    return get_direct_postgres_location(
        schema_name=schema_name,
        schema_metadata=None,
        default_schema=default_schema,
    )


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
    from products.data_warehouse.backend.models.table import DataWarehouseTable

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

    from products.data_warehouse.backend.models.join import DataWarehouseJoin

    DataWarehouseJoin.objects.filter(team_id=team_id, source_table_name=old_name).update(source_table_name=new_name)
    DataWarehouseJoin.objects.filter(team_id=team_id, joining_table_name=old_name).update(joining_table_name=new_name)


def filter_dwh_columns_by_enabled_columns(
    columns: dict[str, _TColumnValue],
    enabled_columns: list[str] | None,
    primary_keys: list[str] | None,
    incremental_field: str | None = None,
) -> dict[str, _TColumnValue]:
    # `None` and `[]` are distinct: `None` means sync all, `[]` means retain only PKs + incremental.
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
    # `None` and `[]` are distinct: `None` means sync all, `[]` means retain only PKs + incremental.
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
    """Persist `schema_metadata` on every Postgres `ExternalDataSchema` and (for direct mode) upsert
    the live-query `DataWarehouseTable`.

    Generalized from the direct-only path so warehouse-mode sources also gain `schema_metadata` for
    multi-schema discovery.
    """
    from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

    is_direct = source.is_direct_query
    source_schema_names = [schema.name for schema in source_schemas]
    default_schema = (source.job_inputs or {}).get("schema")
    schema_models = {
        schema.name: schema
        for schema in ExternalDataSchema.objects.filter(team_id=team_id, source_id=source.id, deleted=False)
    }

    # Build a (source_catalog, source_schema, source_table_name) -> schema_model index so legacy
    # rows whose `name` is unqualified (e.g. "auth_group") still resolve to a discovered qualified
    # schema (e.g. "public.auth_group"). Without this, `available_columns` and `schema_metadata`
    # would only update on the very first refresh and then go stale forever.
    schema_models_by_location: dict[DirectPostgresLocation, ExternalDataSchema] = {}
    for schema_model in schema_models.values():
        location = get_direct_postgres_location_for_schema_model(
            schema_name=schema_model.name,
            sync_type_config=schema_model.sync_type_config,
            table_options=schema_model.table.options if schema_model.table is not None else None,
            default_schema=default_schema,
        )
        # First-write-wins keeps the matching deterministic when a discovered table happens to
        # collide with two existing rows; the rename helper handled the conflict resolution.
        schema_models_by_location.setdefault(location, schema_model)

    for source_schema in source_schemas:
        matched_schema_model: ExternalDataSchema | None = schema_models.get(source_schema.name)
        if matched_schema_model is None:
            location = get_direct_postgres_location(
                schema_name=source_schema.name,
                schema_metadata={
                    "source_catalog": source_schema.source_catalog,
                    "source_schema": source_schema.source_schema,
                    "source_table_name": source_schema.source_table_name,
                },
                default_schema=default_schema,
            )
            matched_schema_model = schema_models_by_location.get(location)
        if matched_schema_model is None:
            continue
        schema_model = matched_schema_model

        resolved_source_catalog, resolved_source_schema, resolved_source_table_name = get_direct_postgres_location(
            schema_name=source_schema.name,
            schema_metadata={
                "source_catalog": source_schema.source_catalog,
                "source_schema": source_schema.source_schema,
                "source_table_name": source_schema.source_table_name,
            },
            default_schema=default_schema,
        )
        # `schema_metadata` carries the FULL column list so the column-picker UI can re-add
        # excluded columns later. Per-row column projection lives on `enabled_columns` separately.
        schema_metadata = postgres_schema_metadata(
            source_schema.columns,
            source_schema.foreign_keys,
            source_catalog=resolved_source_catalog,
            source_schema=resolved_source_schema,
            source_table_name=resolved_source_table_name,
        )
        schema_model.sync_type_config = {**(schema_model.sync_type_config or {}), "schema_metadata": schema_metadata}
        schema_model.save(update_fields=["sync_type_config", "updated_at"])

        if not is_direct:
            # Warehouse mode: ingestion workflow creates/manages `DataWarehouseTable` itself.
            continue

        if not schema_model.should_sync:
            hide_direct_postgres_table(schema_model.table)
            continue

        projected_columns = filter_columns_by_enabled_columns(
            source_schema.columns,
            schema_model.enabled_columns,
            source_schema.detected_primary_keys,
            schema_model.incremental_field,
        )
        table_model = upsert_direct_postgres_table(
            schema_model.table,
            schema_name=source_schema.name,
            source=source,
            columns=postgres_columns_to_dwh_columns(projected_columns),
            source_catalog=resolved_source_catalog,
            source_schema=resolved_source_schema,
            source_table_name=resolved_source_table_name,
        )
        if schema_model.table_id != table_model.id:
            schema_model.table = table_model
            schema_model.save(update_fields=["table"])

    if not is_direct:
        # Warehouse mode: don't soft-delete schemas that vanished from discovery here. The shared
        # `sync_old_schemas_with_new_schemas` path already handles add/delete reconciliation for
        # warehouse rows and is invoked alongside this function in `refresh_schemas`.
        return []

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


def reconcile_direct_postgres_schemas(
    *,
    source: ExternalDataSource,
    source_schemas: list[SourceSchema],
    team_id: int,
) -> list[str]:
    """Deprecated alias retained for callers that pre-date warehouse-mode parity."""
    return reconcile_postgres_schemas(source=source, source_schemas=source_schemas, team_id=team_id)


def rename_direct_postgres_schemas_to_match_source_schemas(
    *,
    source: ExternalDataSource,
    source_schemas: list[SourceSchema],
    team_id: int,
    allow_rename: bool = True,
) -> dict[str, str]:
    """Match discovered source schemas back to existing rows so a multi-schema discovery doesn't
    soft-delete the unqualified row and orphan its DataWarehouseTable.

    Returns a ``{discovered_name: existing_row_name}`` map so the caller can substitute the
    discovered names before invoking ``sync_old_schemas_with_new_schemas`` — without that
    substitution, the unqualified row would be soft-deleted and a fresh qualified row would be
    created in its place, breaking the legacy DataWarehouseTable link.

    When ``allow_rename`` is ``False`` we leave ``ExternalDataSchema.name`` alone but still
    populate ``schema_metadata`` so ``source_for_pipeline`` routes the sync to the right physical
    table. Renaming the row changes the Delta path that ``pipeline_sync`` writes to on the next
    sync, which orphans pre-existing Delta files for warehouse-mode sources. Direct-query mode
    (which has always eager-renamed) opts in via ``allow_rename=True``.
    """
    from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

    default_schema = (source.job_inputs or {}).get("schema")
    schema_models = list(
        ExternalDataSchema.objects.filter(team_id=team_id, source_id=source.id, deleted=False).select_related("table")
    )
    schema_models_by_name = {schema.name: schema for schema in schema_models}
    schema_models_by_location: dict[DirectPostgresLocation, list[ExternalDataSchema]] = {}

    for schema_model in schema_models:
        location = get_direct_postgres_location_for_schema_model(
            schema_name=schema_model.name,
            sync_type_config=schema_model.sync_type_config,
            table_options=schema_model.table.options if schema_model.table is not None else None,
            default_schema=default_schema,
        )
        schema_models_by_location.setdefault(location, []).append(schema_model)

    renamed_schema_ids: set[str] = set()
    name_substitutions: dict[str, str] = {}

    for source_schema in source_schemas:
        if source_schema.name in schema_models_by_name:
            continue

        location = get_direct_postgres_location(
            schema_name=source_schema.name,
            schema_metadata={
                "source_catalog": source_schema.source_catalog,
                "source_schema": source_schema.source_schema,
                "source_table_name": source_schema.source_table_name,
            },
            default_schema=default_schema,
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

        if not allow_rename:
            # Pre-pin the source-side identity so reconcile_postgres_schemas treats the existing
            # row as the canonical match for this discovered table even though the names differ.
            sync_type_config = rename_candidate.sync_type_config or {}
            existing_metadata = sync_type_config.get("schema_metadata")
            if not isinstance(existing_metadata, dict) or not existing_metadata.get("source_table_name"):
                rename_candidate.sync_type_config = {
                    **sync_type_config,
                    "schema_metadata": postgres_schema_metadata(
                        source_schema.columns,
                        source_schema.foreign_keys,
                        source_catalog=source_schema.source_catalog,
                        source_schema=source_schema.source_schema,
                        source_table_name=source_schema.source_table_name,
                    ),
                }
                rename_candidate.save(update_fields=["sync_type_config", "updated_at"])
            # Tell the caller "discovered name X already maps to existing row named Y" so the
            # downstream sync_old_schemas_with_new_schemas pass doesn't try to create a duplicate
            # qualified row or soft-delete the legacy unqualified one.
            name_substitutions[source_schema.name] = rename_candidate.name
            schema_models_by_name[source_schema.name] = rename_candidate
            renamed_schema_ids.add(str(rename_candidate.id))
            continue

        old_name = rename_candidate.name
        rename_candidate.name = source_schema.name
        rename_candidate.save(update_fields=["name", "updated_at"])
        rename_direct_postgres_join_references(team_id=team_id, old_name=old_name, new_name=source_schema.name)
        schema_models_by_name.pop(old_name, None)
        schema_models_by_name[source_schema.name] = rename_candidate
        renamed_schema_ids.add(str(rename_candidate.id))

    return name_substitutions


def _extract_source_location_from_row(row: Any) -> tuple[str | None, str | None]:
    """Return ``(source_schema, source_table_name)`` for an `ExternalDataSchema` row.

    Prefers ``schema_metadata`` (authoritative when reconcile has run); falls back to dot-splitting
    a qualified ``name``. Returns ``(None, None)`` when neither signal is available — e.g. a fresh
    unqualified legacy row without metadata.
    """
    metadata = (row.sync_type_config or {}).get("schema_metadata")
    source_schema: str | None = None
    source_table_name: str | None = None
    if isinstance(metadata, dict):
        source_schema = metadata.get("source_schema") if isinstance(metadata.get("source_schema"), str) else None
        source_table_name = (
            metadata.get("source_table_name") if isinstance(metadata.get("source_table_name"), str) else None
        )
    if (not source_schema or not source_table_name) and "." in row.name:
        inferred_schema, _, inferred_table = row.name.partition(".")
        source_schema = source_schema or inferred_schema or None
        source_table_name = source_table_name or inferred_table or None
    return source_schema, source_table_name


def consolidate_postgres_legacy_rows(
    *,
    source: ExternalDataSource,
    team_id: int,
) -> dict[str, str]:
    """Move legacy unqualified Postgres rows onto the new qualified naming without re-syncing.

    Idempotent. Runs every refresh for warehouse-mode Postgres sources. Handles two states the
    previous schema-clear-only migration missed:

    * The user cleared ``job_inputs.schema`` *before* this migration shipped, leaving both an
      unqualified row (``example_table``, has Delta data) and a refresh-created qualified
      duplicate (``poblic.example_table``, empty) — pin-on-PATCH never re-fires because
      ``job_inputs.schema`` is already blank.
    * Schema is still set but the user wants to migrate ahead of clearing it — qualifying based
      on the configured default schema is safe because reconcile already pointed metadata at the
      right physical table.

    Matching strategy: pair legacy rows to qualified rows by ``source_table_name`` (NOT by full
    ``DirectPostgresLocation``). A legacy row may not have ``schema_metadata`` populated yet —
    reconcile only writes metadata when locations agree, and locations disagree precisely in the
    bug scenario (legacy falls back to ``"public"`` while the discovered row points to
    ``"poblic"``). Cross-pairing on table name alone is the only signal that survives that gap.

    For each legacy row:

    * Qualified duplicate found (shared ``source_table_name``) → soft-delete the qualified
      duplicate (it has no Delta data), rename the legacy in place using the duplicate's
      ``source_schema``, and stash ``dwh_storage_key=<original_name>`` so the Delta path stays
      anchored to the legacy folder.
    * No duplicate, ``job_inputs.schema`` set → qualify to ``"<default_schema>.<name>"`` and
      stash ``dwh_storage_key`` the same way. Safe because the configured schema is precisely
      where the table is being read from today.
    * No duplicate, no default schema → leave alone (we have no signal to pick a schema).

    Returns ``{old_name: new_name}`` for any rows that were renamed or soft-deleted (used by
    callers that need to remap their schema-name dicts before passing them to
    ``sync_old_schemas_with_new_schemas``).
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
            if source_schema is None or source_table_name is None:
                continue
            qualified_rows_by_table_name.setdefault(source_table_name, []).append((source_schema, row))
        else:
            unqualified_rows.append(row)

    default_schema = _normalize_default_schema((source.job_inputs or {}).get("schema"))
    name_substitutions: dict[str, str] = {}

    for legacy in unqualified_rows:
        # Read legacy's own metadata first — `_pin_legacy_postgres_rows_to_default_schema` (PATCH
        # update path) and `reconcile_postgres_schemas` (refresh path) may already have populated
        # `source_schema` to the truthful value. Treat that as the most reliable signal and avoid
        # overwriting it below.
        legacy_sync_type_config = legacy.sync_type_config or {}
        legacy_existing_metadata_raw = legacy_sync_type_config.get("schema_metadata")
        legacy_existing_metadata: dict[str, Any] = (
            dict(legacy_existing_metadata_raw) if isinstance(legacy_existing_metadata_raw, dict) else {}
        )
        legacy_metadata_source_schema = (
            legacy_existing_metadata.get("source_schema")
            if isinstance(legacy_existing_metadata.get("source_schema"), str)
            and legacy_existing_metadata.get("source_schema")
            else None
        )
        legacy_metadata_source_table_name = (
            legacy_existing_metadata.get("source_table_name")
            if isinstance(legacy_existing_metadata.get("source_table_name"), str)
            and legacy_existing_metadata.get("source_table_name")
            else None
        )

        qualified_matches = qualified_rows_by_table_name.get(legacy.name, [])
        # Disambiguate multi-match using legacy's pinned metadata — if legacy already knows it's
        # from `poblic`, prefer the `poblic.example_table` qrow over the `public.example_table` one.
        if len(qualified_matches) > 1 and legacy_metadata_source_schema is not None:
            filtered = [m for m in qualified_matches if m[0] == legacy_metadata_source_schema]
            if len(filtered) == 1:
                qualified_matches = filtered

        if len(qualified_matches) == 1:
            # Exactly one qualified row shares the legacy's table_name — it's typically the
            # refresh-created duplicate. Drop it ONLY if it has no DataWarehouseTable attached;
            # otherwise the user manually synced into it and the duplicate has real data we
            # must not destroy. Skip consolidation in that case and let the user resolve.
            target_source_schema, qrow = qualified_matches[0]
            if qrow.table_id is not None:
                continue
            target_name = qrow.name
            qrow.soft_delete()
            name_substitutions[qrow.name] = target_name
        elif len(qualified_matches) > 1:
            # Multiple qualified rows still point at the same table_name across different schemas
            # even after metadata disambiguation. Can't safely pick a canonical schema — leave the
            # legacy row alone and let the user resolve via the UI.
            continue
        elif legacy_metadata_source_schema is not None:
            # Legacy already has a pinned source_schema (e.g. from a prior `_pin_legacy_postgres_rows_to_default_schema`
            # call when the user cleared `job_inputs.schema`). Trust it over the live default.
            target_source_schema = legacy_metadata_source_schema
            target_name = f"{legacy_metadata_source_schema}.{legacy_metadata_source_table_name or legacy.name}"
        elif default_schema is not None:
            target_source_schema = default_schema
            target_name = f"{default_schema}.{legacy.name}"
        else:
            # No qualified duplicate, no pinned metadata, no default schema configured — nothing to
            # migrate against.
            continue

        merged_metadata: dict[str, Any] = dict(legacy_existing_metadata)
        merged_metadata.setdefault("source_catalog", legacy_existing_metadata.get("source_catalog"))
        # Preserve the truthful metadata if it was already set — don't clobber a deliberately-set
        # `source_schema` (e.g. CDC row with explicit schema) with the default-schema fallback.
        merged_metadata["source_schema"] = legacy_metadata_source_schema or target_source_schema
        merged_metadata["source_table_name"] = legacy_metadata_source_table_name or legacy.name
        merged_metadata.setdefault("columns", [])
        merged_metadata.setdefault("foreign_keys", [])

        new_sync_type_config: dict[str, Any] = {
            **legacy_sync_type_config,
            "schema_metadata": merged_metadata,
        }
        if "dwh_storage_key" not in legacy_sync_type_config:
            # Lock the Delta storage path to the legacy unqualified key so existing files stay
            # readable. validate_schema_and_update_table reads this back instead of recomputing.
            new_sync_type_config["dwh_storage_key"] = legacy.name

        original_name = legacy.name
        legacy.name = target_name
        legacy.sync_type_config = new_sync_type_config
        legacy.save(update_fields=["name", "sync_type_config", "updated_at"])
        name_substitutions[original_name] = target_name

    return name_substitutions
