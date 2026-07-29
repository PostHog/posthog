"""Expose a managed Duckgres warehouse in the SQL editor as a Postgres connection.

Each member team gets a Postgres ``ExternalDataSource`` pointed at the organization's
``DuckgresServer``, authenticated with the server's org root credential. Duckgres root
sees every schema in the warehouse, so the connection discovers and exposes the whole
org catalog without per-team namespace configuration — no control-plane handshake is
involved in setting it up. Setup happens in two steps:

1. ``ensure_managed_warehouse_direct_source`` creates the source row when a team
   joins, so the connection appears immediately.
2. ``reconcile_managed_warehouse_tables`` runs once the warehouse is ready and records
   every non-internal schema/table the root credential can see.

This bypasses the user-facing create endpoint because the managed host is internal
infrastructure and is not reachable for live schema validation during provisioning.

Lifecycle is org-level only: ``soft_delete_managed_warehouse_sources`` handles
deprovisioning of the whole warehouse. There is no per-team offboarding flow yet —
a single team leaving keeps its connection until the org deprovisions (revisit if
per-team removal becomes a product flow).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

import structlog

from posthog.models.team.team import Team

from products.data_warehouse.backend.postgres_helpers import reconcile_postgres_schemas
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import (
    MANAGED_WAREHOUSE_SOURCE_PREFIX,
    ExternalDataSource,
)
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry

if TYPE_CHECKING:
    from posthog.ducklake.models import DuckgresServer

logger = structlog.get_logger(__name__)

MANAGED_WAREHOUSE_SOURCE_DESCRIPTION = "Managed warehouse (auto-provisioned)"

# Database engine internals — never warehouse data. Sidebar hygiene, not permissioning:
# root bypasses Duckgres AllowedSchemas, so this denylist is the only filter on what the
# discover sweep registers. The later per-schema visibility control plugs in here.
INTERNAL_SCHEMAS = frozenset({"pg_catalog", "information_schema", "pg_toast", "system"})


def internal_schemas() -> set[str]:
    """The schemas the discover sweep must never register as warehouse tables."""
    return set(INTERNAL_SCHEMAS)


def _managed_source_queryset(team_id: int) -> QuerySet[ExternalDataSource]:
    return ExternalDataSource._base_manager.filter(
        team_id=team_id,
        source_type=ExternalDataSourceType.POSTGRES,
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        connection_metadata__system_managed=True,
    )


def _source_config(server: DuckgresServer) -> dict[str, object]:
    """Snapshot the server's org root credential into the source's job_inputs."""
    source_impl = SourceRegistry.get_source(ExternalDataSourceType.POSTGRES)
    return source_impl.parse_config(
        {
            "host": server.host,
            "port": server.port,
            "database": server.database,
            "user": server.username,
            "password": server.password,
        }
    ).to_dict()


def _ensure_managed_source_locked(*, team_id: int, server: DuckgresServer) -> ExternalDataSource:
    # Deliberately includes soft-deleted rows: a re-enabled membership revives its
    # tombstoned source.
    existing = _managed_source_queryset(team_id).select_for_update().order_by("-created_at").first()

    config = _source_config(server)
    if existing is not None:
        update_fields: list[str] = []
        connection_metadata = dict(existing.connection_metadata or {})
        if connection_metadata.get("credential_kind") not in ("org_root", "project_reader"):
            # Old managed sources predate the project-reader credential boundary, so
            # discard any catalog entries discovered before Duckgres enforced it.
            now = timezone.now()
            DataWarehouseTable.raw_objects.filter(
                team_id=team_id, external_data_source_id=existing.id, deleted=False
            ).update(deleted=True, deleted_at=now, updated_at=now)
            ExternalDataSchema.objects.filter(team_id=team_id, source_id=existing.id).delete()
        if existing.job_inputs != config:
            existing.job_inputs = config
            update_fields.append("job_inputs")
        if existing.access_method != ExternalDataSource.AccessMethod.DIRECT:
            existing.access_method = ExternalDataSource.AccessMethod.DIRECT
            update_fields.append("access_method")
        if not existing.direct_query_enabled:
            existing.direct_query_enabled = True
            update_fields.append("direct_query_enabled")
        if (
            connection_metadata.get("engine") != "duckdb"
            or connection_metadata.get("system_managed") is not True
            or connection_metadata.get("credential_kind") != "org_root"
        ):
            migrated = {
                **connection_metadata,
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "org_root",
            }
            migrated.pop("reader_configured", None)
            existing.connection_metadata = migrated
            update_fields.append("connection_metadata")
        if existing.deleted:
            existing.deleted = False
            existing.deleted_at = None
            update_fields.extend(["deleted", "deleted_at"])
        if update_fields:
            existing.save(update_fields=[*update_fields, "updated_at"])
        return existing

    return ExternalDataSource.objects.create(
        source_id=str(uuid4()),
        connection_id=str(uuid4()),
        destination_id=str(uuid4()),
        team_id=team_id,
        status=ExternalDataSource.Status.RUNNING,
        source_type=ExternalDataSourceType.POSTGRES,
        job_inputs=config,
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        description=MANAGED_WAREHOUSE_SOURCE_DESCRIPTION,
        access_method=ExternalDataSource.AccessMethod.DIRECT,
        created_via=ExternalDataSource.CreatedVia.WEB,
        direct_query_enabled=True,
        connection_metadata={
            "engine": "duckdb",
            "system_managed": True,
            "credential_kind": "org_root",
        },
    )


def ensure_managed_warehouse_direct_source(*, team_id: int, organization_id: str | UUID) -> ExternalDataSource:
    """Create or refresh the team's managed-warehouse query source on the org root credential."""
    from posthog.ducklake.models import DuckgresServer  # noqa: PLC0415

    with transaction.atomic():
        server = DuckgresServer.objects.select_for_update().get(organization_id=organization_id)
        Team.objects.select_for_update().only("id").get(id=team_id, organization_id=organization_id)
        return _ensure_managed_source_locked(team_id=team_id, server=server)


def reconcile_managed_warehouse_tables(*, team_id: int, organization_id: str | UUID) -> None:
    """Discover and register the org-wide managed-warehouse catalog for this team's source."""
    from posthog.ducklake.models import DuckgresServer  # noqa: PLC0415

    with transaction.atomic():
        # Check before ensure: a tombstoned source means the warehouse was deprovisioned
        # (its DuckgresServer row is deleted synchronously), and nothing may revive it —
        # otherwise this sweep would resurrect sources right after deprovision.
        if _managed_source_queryset(team_id).filter(deleted=True).exists():
            return

    try:
        ensure_managed_warehouse_direct_source(team_id=team_id, organization_id=organization_id)
    except (DuckgresServer.DoesNotExist, Team.DoesNotExist):
        return

    with transaction.atomic():
        server = DuckgresServer.objects.select_for_update().filter(organization_id=organization_id).first()
        team = Team.objects.select_for_update().only("id").filter(id=team_id, organization_id=organization_id).first()
        if server is None or team is None:
            return

        source = _managed_source_queryset(team_id).select_for_update().filter(deleted=False).first()
        if source is None:
            return
        source_id = source.id
        source_config = dict(source.job_inputs or {})
        source_api_version = source.api_version

    excluded_schemas = internal_schemas()

    source_impl = SourceRegistry.get_source(ExternalDataSourceType.POSTGRES)
    config = source_impl.parse_config(source_config)
    try:
        discovered = source_impl.get_schemas(
            config, team_id, api_version=source_impl.resolve_api_version(source_api_version)
        )
    except Exception:
        # A provisioning or briefly unreachable warehouse fails here on every periodic sweep;
        # skip and let the next run retry rather than surfacing a task error each time.
        logger.warning("Managed warehouse introspection failed; will retry", team_id=team_id, exc_info=True)
        return
    source_schemas = [schema for schema in discovered if (schema.source_schema or "") not in excluded_schemas]
    if not source_schemas:
        return

    with transaction.atomic():
        # Revalidate after live introspection so deprovision wins the race.
        server = DuckgresServer.objects.select_for_update().filter(organization_id=organization_id).first()
        team = Team.objects.select_for_update().only("id").filter(id=team_id, organization_id=organization_id).first()
        if server is None or team is None:
            return
        source = (
            _managed_source_queryset(team_id)
            .select_for_update()
            .filter(
                id=source_id,
                deleted=False,
                access_method=ExternalDataSource.AccessMethod.DIRECT,
                direct_query_enabled=True,
            )
            .first()
        )
        if source is None:
            return

        for schema in source_schemas:
            schema_model, _created = ExternalDataSchema.objects.get_or_create(
                team_id=team_id,
                source=source,
                name=schema.name,
                defaults={"should_sync": True, "sync_type": None, "sync_type_config": {}},
            )
            if schema_model.deleted:
                schema_model.deleted = False
                schema_model.deleted_at = None
                schema_model.should_sync = True
                schema_model.save(update_fields=["deleted", "deleted_at", "should_sync", "updated_at"])

        reconcile_postgres_schemas(source=source, source_schemas=source_schemas, team_id=team_id)


def _managed_sources_for_org(organization_id: str | UUID) -> QuerySet[ExternalDataSource]:
    return ExternalDataSource._base_manager.filter(
        team__organization_id=organization_id,
        source_type=ExternalDataSourceType.POSTGRES,
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        connection_metadata__system_managed=True,
    ).exclude(deleted=True)


def update_managed_warehouse_root_password(*, organization_id: str | UUID, password: str) -> None:
    """Rotate the root password on the server row and every managed source of the org.

    Each source snapshots the root credential into its ``job_inputs``, so a rotation must
    fan out to all of them in the same transaction — otherwise every source holds a stale
    password and fails silently.
    """
    from posthog.ducklake.models import DuckgresServer  # noqa: PLC0415

    with transaction.atomic():
        server = DuckgresServer.objects.select_for_update().get(organization_id=organization_id)
        server.password = password
        server.save(update_fields=["password", "updated_at"])

        config = _source_config(server)
        for source in _managed_sources_for_org(organization_id).select_for_update().order_by("team_id"):
            if source.job_inputs != config:
                source.job_inputs = config
                source.save(update_fields=["job_inputs", "updated_at"])


def soft_delete_managed_warehouse_sources(*, organization_id: str | UUID) -> None:
    """Atomically tombstone the organization's managed query sources on deprovision.

    Per-team state needs no disabling here: deprovisioning removes the org's team rows
    from the duckgres control plane, which is the read source for membership.
    """
    from posthog.ducklake.models import DuckgresServer  # noqa: PLC0415

    now = timezone.now()
    with transaction.atomic():
        DuckgresServer.objects.select_for_update().filter(organization_id=organization_id).first()
        sources = list(_managed_sources_for_org(organization_id).select_for_update().order_by("team_id"))
        DataWarehouseTable.raw_objects.filter(
            external_data_source_id__in=[source.id for source in sources], deleted=False
        ).update(deleted=True, deleted_at=now, updated_at=now)
        for source in sources:
            source.deleted = True
            source.deleted_at = now
            source.save(update_fields=["deleted", "deleted_at", "updated_at"])
