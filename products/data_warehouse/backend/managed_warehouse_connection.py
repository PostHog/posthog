"""Bridge a provisioned managed (duckgres) warehouse into the SQL editor as a Postgres
direct connection.

A managed warehouse speaks the Postgres wire protocol, so each team that provisions or
joins one gets an ``ExternalDataSource`` (``postgres`` / ``direct``) pointed at the org's
``DuckgresServer``. The connection is created in two decoupled steps:

  1. ``ensure_managed_warehouse_direct_source`` — runs at provision / team-join. Creates the
     (initially empty) source row so the connection shows up in the SQL editor immediately,
     before the warehouse is reachable.
  2. ``reconcile_managed_warehouse_tables`` — runs once the warehouse reports ``ready``.
     Introspects the team's ``events_<suffix>`` / ``persons_<suffix>`` tables and upserts
     the ``ExternalDataSchema`` + live-query ``DataWarehouseTable`` rows that make them
     queryable.

This deliberately bypasses the user-facing create endpoint: that path runs an SSRF host
check (the managed host is internal infra we control) and a live schema probe (the endpoint
isn't reachable at provision time).
"""

from __future__ import annotations

from uuid import UUID, uuid4

from django.utils import timezone

import structlog

from products.data_warehouse.backend.direct_postgres import hide_direct_postgres_table
from products.data_warehouse.backend.postgres_helpers import reconcile_postgres_schemas
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)

# Identifies the auto-created direct source so it can be found again (dedup, password rotation,
# deprovision cleanup) without colliding with a user's own Postgres source.
MANAGED_WAREHOUSE_SOURCE_PREFIX = "managed_warehouse"
MANAGED_WAREHOUSE_SOURCE_DESCRIPTION = "Managed warehouse (auto-provisioned)"


def managed_warehouse_table_names(table_suffix: str | None) -> list[str]:
    """The duckgres tables a team writes to: per-environment when it has a suffix, else shared."""
    if table_suffix:
        return [f"events_{table_suffix}", f"persons_{table_suffix}"]
    return ["events", "persons"]


def _find_managed_source(team_id: int) -> ExternalDataSource | None:
    return (
        ExternalDataSource.objects.filter(
            team_id=team_id,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        )
        .exclude(deleted=True)
        .first()
    )


def ensure_managed_warehouse_direct_source(
    *,
    team_id: int,
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
) -> ExternalDataSource | None:
    """Create the team's Postgres direct source for the managed warehouse, if absent.

    Idempotent: returns the existing managed source when one is already present. The row is
    created empty (no schemas/tables) — discovery happens later in
    ``reconcile_managed_warehouse_tables`` once the warehouse is reachable.
    """
    existing = _find_managed_source(team_id)
    if existing is not None:
        return existing

    # Normalize the connection through the source's own config so ``job_inputs`` matches the
    # shape the reconcile/query paths read back (the same call the create endpoint makes).
    source_impl = SourceRegistry.get_source(ExternalDataSourceType.POSTGRES)
    config = source_impl.parse_config(
        {
            "host": host,
            "port": port,
            "database": database,
            "user": username,
            "password": password,
        }
    )

    return ExternalDataSource.objects.create(
        source_id=str(uuid4()),
        connection_id=str(uuid4()),
        destination_id=str(uuid4()),
        team_id=team_id,
        status=ExternalDataSource.Status.RUNNING,
        source_type=ExternalDataSourceType.POSTGRES,
        job_inputs=config.to_dict(),
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        description=MANAGED_WAREHOUSE_SOURCE_DESCRIPTION,
        access_method=ExternalDataSource.AccessMethod.DIRECT,
        created_via=ExternalDataSource.CreatedVia.WEB,
        direct_query_enabled=True,
    )


def reconcile_managed_warehouse_tables(*, team_id: int, organization_id: str | UUID) -> None:
    """Discover and upsert the team's managed-warehouse tables once the warehouse is reachable.

    Self-heals the source row (creates it if it went missing), then introspects only the team's
    ``events_<suffix>`` / ``persons_<suffix>`` tables and reuses ``reconcile_postgres_schemas``
    to build their live-query ``DataWarehouseTable`` rows. Cheap to call repeatedly: once both
    tables exist it returns before opening a live connection, so the warehouse-status poll that
    drives it doesn't re-introspect on every tick.
    """
    # Imported here (not at module top) to keep duckgres model access off the import path of
    # callers that only need the lightweight creation helpers.
    from posthog.ducklake.models import DuckgresServer, DuckgresServerTeam  # noqa: PLC0415

    server = DuckgresServer.objects.filter(organization_id=organization_id).first()
    if server is None:
        return

    membership = DuckgresServerTeam.objects.filter(team_id=team_id).values("table_suffix").first()
    if membership is None:
        # The team hasn't joined the warehouse — don't expose a connection it didn't opt into.
        return
    table_suffix = membership["table_suffix"]

    source = ensure_managed_warehouse_direct_source(
        team_id=team_id,
        host=server.host,
        port=server.port,
        database=server.database,
        username=server.username,
        password=server.password,
    )
    if source is None:
        return

    expected = managed_warehouse_table_names(table_suffix)
    existing_tables = set(
        DataWarehouseTable.raw_objects.queryable()
        .filter(team_id=team_id, external_data_source_id=source.id)
        .values_list("name", flat=True)
    )
    if all(name in existing_tables for name in expected):
        return

    source_impl = SourceRegistry.get_source(ExternalDataSourceType.POSTGRES)
    config = source_impl.parse_config(source.job_inputs or {})
    source_schemas = [
        schema
        for schema in source_impl.get_schemas(config, team_id, names=expected)
        if schema.source_table_name in expected or schema.name in expected
    ]
    if not source_schemas:
        return

    for schema in source_schemas:
        ExternalDataSchema.objects.get_or_create(
            team_id=team_id,
            source=source,
            name=schema.name,
            defaults={"should_sync": True, "sync_type": None, "sync_type_config": {}},
        )

    reconcile_postgres_schemas(source=source, source_schemas=source_schemas, team_id=team_id)


def _managed_sources_for_org(organization_id: str | UUID):
    return (
        ExternalDataSource.objects.filter(
            team__organization_id=organization_id,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        )
        .exclude(deleted=True)
        .iterator()
    )


def update_managed_warehouse_password(*, organization_id: str | UUID, password: str) -> None:
    """Refresh the stored connection password for every team's managed source after a rotation.

    Without this, live queries break the moment the control-plane password is reset.
    """
    for source in _managed_sources_for_org(organization_id):
        job_inputs = dict(source.job_inputs or {})
        job_inputs["password"] = password
        source.job_inputs = job_inputs
        source.save(update_fields=["job_inputs", "updated_at"])


def soft_delete_managed_warehouse_sources(*, organization_id: str | UUID) -> None:
    """Soft-delete the org's managed direct sources and their tables on deprovision."""
    now = timezone.now()
    for source in _managed_sources_for_org(organization_id):
        for table in DataWarehouseTable.raw_objects.queryable().filter(
            team_id=source.team_id, external_data_source_id=source.id
        ):
            hide_direct_postgres_table(table)
        source.deleted = True
        source.deleted_at = now
        source.save(update_fields=["deleted", "deleted_at", "updated_at"])
