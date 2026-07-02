"""Postgres-specific refresh reconciliation.

The source-agnostic migration lives in `sql_warehouse_migration.py`; this keeps only the Postgres +
direct-query plumbing — combining the rename helper with the shared `apply_on_refresh` into one
substitution dict for `sync_old_schemas_with_new_schemas`.
"""

from __future__ import annotations

from products.data_warehouse.backend.postgres_helpers import rename_postgres_schemas_to_match_source_schemas
from products.data_warehouse.backend.sql_warehouse_migration import apply_on_refresh
from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema


def reconcile_refresh_name_substitutions(
    *,
    source: ExternalDataSource,
    source_schemas: list[SourceSchema],
    team_id: int,
) -> dict[str, str]:
    """Compute name substitutions for a Postgres refresh — combines the rename helper (direct mode
    eager rename / warehouse metadata pin) with the consolidate helper (warehouse-mode qualify in
    place) and chains them so the caller feeds a single dict to `sync_old_schemas_with_new_schemas`.
    """
    name_substitutions = rename_postgres_schemas_to_match_source_schemas(
        source=source,
        source_schemas=source_schemas,
        team_id=team_id,
        # Warehouse-mode rename would change the Delta path on the next sync; defer to consolidate
        # below which preserves the path via `s3_folder_name`.
        allow_rename=source.is_direct_query,
    )

    if not source.is_direct_query:
        consolidation_substitutions = apply_on_refresh(source=source, team_id=team_id)
        # Chain {discovered: existing} → {discovered: renamed} when consolidate renamed `existing`.
        for old_name, new_name in consolidation_substitutions.items():
            for discovered, existing in list(name_substitutions.items()):
                if existing == old_name:
                    name_substitutions[discovered] = new_name
        name_substitutions = {**name_substitutions, **consolidation_substitutions}
        name_substitutions = {k: v for k, v in name_substitutions.items() if k != v}

    return name_substitutions
