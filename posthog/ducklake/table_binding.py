from __future__ import annotations

import logging
from typing import Any

from posthog.ducklake.common import (
    duckgres_data_imports_schema,
    duckgres_data_imports_table_name,
    duckgres_data_modeling_schema,
    duckgres_data_modeling_table_name,
)

logger = logging.getLogger(__name__)


def bind_tables_to_ducklake(database: Any, team_id: int) -> None:
    """Bind a built HogQL database's tables to their duckgres-materialized counterparts.

    Rebind the logical PostHog, data-modeling, and imported source table names to
    the physical names written for this team in the Duckgres cluster.

    Mutates ``database`` in place. Scoped to the DuckLake compile path only — the
    ClickHouse path never calls this, so its table resolution is unchanged.
    """
    _bind_posthog_tables(database, team_id)
    _bind_materialized_models(database, team_id)
    _bind_source_tables(database, team_id)


def _bind_posthog_tables(database: Any, team_id: int) -> None:
    """Bind built-in events and persons tables to the team's cluster tables."""
    from posthog.hogql.database.direct_postgres_table import DirectPostgresTable

    from posthog.ducklake.team_state import resolve_events_persons_tables

    physical_names = dict(zip(("events", "persons"), resolve_events_persons_tables(team_id), strict=True))
    for logical_name, physical_name in physical_names.items():
        node = database.get_table_node([logical_name])
        existing = node.table
        if existing is None:
            continue
        node.table = DirectPostgresTable(
            name=logical_name,
            external_data_source_id="",
            postgres_schema="posthog",
            postgres_table_name=physical_name,
            fields=existing.fields,
        )


def _bind_materialized_models(database: Any, team_id: int) -> None:
    """Bind materialized data-modeling models to their DuckLake schema (``shadow_<team_id>_models``)."""
    from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
    from posthog.hogql.errors import ResolutionError

    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

    schema_name = duckgres_data_modeling_schema(team_id)
    materialized = DataWarehouseSavedQuery.objects.filter(
        team_id=team_id, is_materialized=True, table__isnull=False
    ).exclude(deleted=True)
    for saved_query in materialized:
        try:
            node = database.get_table_node(saved_query.name.split("."))
        except ResolutionError:
            logger.debug("Model %s not in HogQL database; skipping DuckLake bind", saved_query.name)
            continue
        existing = node.table
        if existing is None:
            continue
        node.table = DirectPostgresTable(
            name=saved_query.name,
            external_data_source_id="",
            postgres_schema=schema_name,
            postgres_table_name=duckgres_data_modeling_table_name(saved_query.name),
            fields=existing.fields,
        )


def _bind_source_tables(database: Any, team_id: int) -> None:
    """Bind imported source tables to their DuckLake-copied counterparts.

    Each queryable, S3-backed warehouse table that has a linked ``ExternalDataSchema`` was
    copied into the team's data-imports schema by the copy workflow. Model backing tables
    have no schema, so they are naturally skipped; direct-query tables already render
    schema-qualified and are not S3-backed, so they are skipped too. The binding is blind —
    if a table hasn't been synced yet, duckgres errors at query time, which is intended.
    """
    from posthog.hogql.database.database import get_data_warehouse_table_name
    from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
    from posthog.hogql.errors import ResolutionError

    from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource

    schema_name = duckgres_data_imports_schema(team_id)
    tables = (
        DataWarehouseTable.objects.queryable()
        .filter(team_id=team_id, external_data_source__isnull=False)
        .exclude(external_data_source__access_method=ExternalDataSource.AccessMethod.DIRECT)
        .select_related("external_data_source")
        .prefetch_related("externaldataschema_set__source")
    )
    for table in tables:
        external_schema = next(iter(table.externaldataschema_set.all()), None)
        if external_schema is None:
            continue

        name_chains = [table.name_chain]
        logical_name_chain = get_data_warehouse_table_name(table.external_data_source, table.name).split(".")
        if logical_name_chain != table.name_chain:
            name_chains.append(logical_name_chain)

        physical_table_name = duckgres_data_imports_table_name(external_schema)
        for name_chain in name_chains:
            try:
                node = database.get_table_node(name_chain)
            except ResolutionError:
                logger.debug("Source table %s not in HogQL database; skipping DuckLake bind", ".".join(name_chain))
                continue
            existing = node.table
            if existing is None:
                continue
            node.table = DirectPostgresTable(
                name=".".join(name_chain),
                external_data_source_id="",
                postgres_schema=schema_name,
                postgres_table_name=physical_table_name,
                fields=existing.fields,
            )
