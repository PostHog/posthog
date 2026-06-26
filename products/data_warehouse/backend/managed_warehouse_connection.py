"""Expose a managed Duckgres warehouse in the SQL editor as a restricted Postgres connection.

Each member team gets a Postgres ``ExternalDataSource`` pointed at the organization's
``DuckgresServer``. It uses warehouse access mode with live querying enabled: HogQL can query
only registered team tables, while unrestricted raw SQL is rejected. Setup happens in two steps:

1. ``ensure_managed_warehouse_direct_source`` creates the initially empty source row when a team
   joins, so the connection appears immediately.
2. ``reconcile_managed_warehouse_tables`` runs once the warehouse is ready and records schema
   metadata for the team's events and persons tables.

This bypasses the user-facing create endpoint because the managed host is internal infrastructure
and is not reachable for live schema validation during provisioning.
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


def managed_warehouse_table_names(table_suffix: str) -> list[str]:
    """Return the Duckgres tables owned by a team."""
    return [f"events_{table_suffix}", f"persons_{table_suffix}"]


def _managed_source_queryset(team_id: int) -> QuerySet[ExternalDataSource]:
    return ExternalDataSource._base_manager.filter(
        team_id=team_id,
        source_type=ExternalDataSourceType.POSTGRES,
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        connection_metadata__system_managed=True,
    )


def _source_config(server: DuckgresServer) -> dict[str, object]:
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


def _ensure_managed_source_locked(
    *, team_id: int, server: DuckgresServer, reactivate_deleted: bool
) -> ExternalDataSource | None:
    existing = _managed_source_queryset(team_id).select_for_update().order_by("-created_at").first()
    if existing is not None and existing.deleted and not reactivate_deleted:
        # Deprovision leaves a tombstone so a queued status task cannot recreate the source.
        return None

    config = _source_config(server)
    if existing is not None:
        update_fields: list[str] = []
        if existing.access_method == ExternalDataSource.AccessMethod.DIRECT:
            # Upgrade rows created by an earlier version that allowed unrestricted raw SQL.
            now = timezone.now()
            DataWarehouseTable.raw_objects.filter(
                team_id=team_id, external_data_source_id=existing.id, deleted=False
            ).update(deleted=True, deleted_at=now, updated_at=now)
            ExternalDataSchema.objects.filter(team_id=team_id, source_id=existing.id).delete()
        if existing.job_inputs != config:
            existing.job_inputs = config
            update_fields.append("job_inputs")
        if existing.access_method != ExternalDataSource.AccessMethod.WAREHOUSE:
            existing.access_method = ExternalDataSource.AccessMethod.WAREHOUSE
            update_fields.append("access_method")
        if not existing.direct_query_enabled:
            existing.direct_query_enabled = True
            update_fields.append("direct_query_enabled")
        connection_metadata = dict(existing.connection_metadata or {})
        if connection_metadata.get("engine") != "duckdb" or connection_metadata.get("system_managed") is not True:
            existing.connection_metadata = {**connection_metadata, "engine": "duckdb", "system_managed": True}
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
        access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
        created_via=ExternalDataSource.CreatedVia.WEB,
        direct_query_enabled=True,
        connection_metadata={"engine": "duckdb", "system_managed": True},
    )


def ensure_managed_warehouse_direct_source(*, team_id: int, organization_id: str | UUID) -> ExternalDataSource:
    """Create or refresh the team's restricted live-query source from its membership."""
    from posthog.ducklake.models import DuckgresServer, DuckgresServerTeam  # noqa: PLC0415

    with transaction.atomic():
        # All lifecycle mutations use server -> team -> source lock order. Password rotation
        # therefore cannot commit between reading the server password and creating this row.
        server = DuckgresServer.objects.select_for_update().get(organization_id=organization_id)
        Team.objects.select_for_update().only("id").get(id=team_id, organization_id=organization_id)
        membership = (
            DuckgresServerTeam.objects.select_for_update()
            .filter(server=server, team_id=team_id, backfill_enabled=True)
            .values("table_suffix")
            .first()
        )
        if membership is None:
            raise ValueError("The team has not joined this managed warehouse")
        if not membership["table_suffix"]:
            raise ValueError("Legacy shared managed warehouse tables cannot be exposed as a query connection")

        source = _ensure_managed_source_locked(team_id=team_id, server=server, reactivate_deleted=True)
        if source is None:
            raise RuntimeError("Failed to create the managed warehouse query source")
        return source


def _registered_managed_table_names(*, team_id: int, source_id: UUID) -> set[str]:
    registered: set[str] = set()
    rows = ExternalDataSchema.objects.filter(
        team_id=team_id,
        source_id=source_id,
        should_sync=True,
        deleted=False,
    ).values_list("name", "sync_type_config")
    for name, sync_type_config in rows:
        metadata = sync_type_config.get("schema_metadata") if isinstance(sync_type_config, dict) else None
        source_table_name = metadata.get("source_table_name") if isinstance(metadata, dict) else None
        registered.add(source_table_name if isinstance(source_table_name, str) else name.rsplit(".", 1)[-1])
    return registered


def reconcile_managed_warehouse_tables(*, team_id: int, organization_id: str | UUID) -> None:
    """Discover and register only this team's managed-warehouse tables."""
    from posthog.ducklake.models import DuckgresServer, DuckgresServerTeam  # noqa: PLC0415

    with transaction.atomic():
        server = DuckgresServer.objects.select_for_update().filter(organization_id=organization_id).first()
        team = Team.objects.select_for_update().only("id").filter(id=team_id, organization_id=organization_id).first()
        if server is None or team is None:
            return

        membership_data = (
            DuckgresServerTeam.objects.select_for_update()
            .filter(
                server=server,
                team_id=team_id,
                team__organization_id=organization_id,
                backfill_enabled=True,
            )
            .values("table_suffix")
            .first()
        )
        if membership_data is None:
            return

        table_suffix = membership_data["table_suffix"]
        if not table_suffix:
            # Legacy tables are shared across teams and require a team_id predicate that direct HogQL cannot enforce.
            return
        source = _ensure_managed_source_locked(team_id=team_id, server=server, reactivate_deleted=False)
        if source is None:
            return
        expected = managed_warehouse_table_names(table_suffix)
        if set(expected) <= _registered_managed_table_names(team_id=team_id, source_id=source.id):
            return
        source_id = source.id
        source_config = dict(source.job_inputs or {})

    source_impl = SourceRegistry.get_source(ExternalDataSourceType.POSTGRES)
    config = source_impl.parse_config(source_config)
    source_schemas = [
        schema
        for schema in source_impl.get_schemas(config, team_id, names=expected)
        if schema.source_table_name in expected or schema.name in expected
    ]
    if not source_schemas:
        return

    with transaction.atomic():
        # Revalidate after live introspection so deprovision or membership removal wins the race.
        server = DuckgresServer.objects.select_for_update().filter(organization_id=organization_id).first()
        team = Team.objects.select_for_update().only("id").filter(id=team_id, organization_id=organization_id).first()
        if server is None or team is None:
            return
        membership = (
            DuckgresServerTeam.objects.select_for_update()
            .filter(
                server=server,
                team_id=team_id,
                team__organization_id=organization_id,
                table_suffix=table_suffix,
                backfill_enabled=True,
            )
            .first()
        )
        source = (
            _managed_source_queryset(team_id)
            .select_for_update()
            .filter(
                id=source_id,
                deleted=False,
                access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
                direct_query_enabled=True,
            )
            .first()
        )
        if membership is None or source is None:
            return

        for schema in source_schemas:
            ExternalDataSchema.objects.get_or_create(
                team_id=team_id,
                source=source,
                name=schema.name,
                defaults={"should_sync": True, "sync_type": None, "sync_type_config": {}},
            )

        reconcile_postgres_schemas(source=source, source_schemas=source_schemas, team_id=team_id)


def _managed_sources_for_org(organization_id: str | UUID) -> QuerySet[ExternalDataSource]:
    return ExternalDataSource._base_manager.filter(
        team__organization_id=organization_id,
        source_type=ExternalDataSourceType.POSTGRES,
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        connection_metadata__system_managed=True,
    ).exclude(deleted=True)


def update_managed_warehouse_password(*, organization_id: str | UUID, password: str) -> None:
    """Atomically refresh the authoritative password and every live query source."""
    from posthog.ducklake.models import DuckgresServer  # noqa: PLC0415

    with transaction.atomic():
        server = DuckgresServer.objects.select_for_update().get(organization_id=organization_id)
        list(
            Team.objects.select_for_update()
            .filter(organization_id=organization_id)
            .order_by("id")
            .values_list("id", flat=True)
        )
        sources = list(_managed_sources_for_org(organization_id).select_for_update().order_by("team_id"))
        server.password = password
        server.save(update_fields=["password", "updated_at"])
        for source in sources:
            job_inputs = dict(source.job_inputs or {})
            job_inputs["password"] = password
            source.job_inputs = job_inputs
            source.save(update_fields=["job_inputs", "updated_at"])


def soft_delete_managed_warehouse_sources(*, organization_id: str | UUID) -> None:
    """Atomically tombstone the organization's managed query sources on deprovision."""
    from posthog.ducklake.models import DuckgresServer, DuckgresServerTeam  # noqa: PLC0415

    now = timezone.now()
    with transaction.atomic():
        DuckgresServer.objects.select_for_update().filter(organization_id=organization_id).first()
        list(
            Team.objects.select_for_update()
            .filter(organization_id=organization_id)
            .order_by("id")
            .values_list("id", flat=True)
        )
        sources = list(_managed_sources_for_org(organization_id).select_for_update().order_by("team_id"))
        DuckgresServerTeam.objects.filter(server__organization_id=organization_id).update(backfill_enabled=False)
        DataWarehouseTable.raw_objects.filter(
            external_data_source_id__in=[source.id for source in sources], deleted=False
        ).update(deleted=True, deleted_at=now, updated_at=now)
        for source in sources:
            source.deleted = True
            source.deleted_at = now
            source.save(update_fields=["deleted", "deleted_at", "updated_at"])
