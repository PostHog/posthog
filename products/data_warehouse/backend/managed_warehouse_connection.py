"""Expose a managed Duckgres warehouse in the SQL editor as a read-only Postgres connection.

Each member team gets a Postgres ``ExternalDataSource`` pointed at the organization's
``DuckgresServer``. Duckgres issues a distinct database login for each project and enforces
read-only access to the project's schemas, so both HogQL and raw SQL stay inside that boundary.
Setup happens in two steps:

1. ``ensure_managed_warehouse_direct_source`` creates the initially empty source row when a team
   joins, so the connection appears immediately.
2. ``reconcile_managed_warehouse_tables`` runs once the warehouse is ready and records every
   table in the project's event/person, data-import, team, and modeled-data namespaces.

This bypasses the user-facing create endpoint because the managed host is internal infrastructure
and is not reachable for live schema validation during provisioning.

Lifecycle is org-level only: ``soft_delete_managed_warehouse_sources`` handles deprovisioning of
the whole warehouse. There is no per-team offboarding flow yet — a single team leaving keeps its
connection until the org deprovisions (revisit if per-team removal becomes a product flow).
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

import structlog

from posthog.models.team.team import Team

from products.data_warehouse.backend.postgres_helpers import reconcile_postgres_schemas
from products.data_warehouse.backend.presentation.views import managed_warehouse
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


def _managed_source_queryset(team_id: int) -> QuerySet[ExternalDataSource]:
    return ExternalDataSource._base_manager.filter(
        team_id=team_id,
        source_type=ExternalDataSourceType.POSTGRES,
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        connection_metadata__system_managed=True,
    )


def _source_config(server: DuckgresServer, *, username: str, password: str) -> dict[str, object]:
    source_impl = SourceRegistry.get_source(ExternalDataSourceType.POSTGRES)
    return source_impl.parse_config(
        {
            "host": server.host,
            "port": server.port,
            "database": server.database,
            "user": username,
            "password": password,
        }
    ).to_dict()


def _ensure_managed_source_locked(
    *,
    team_id: int,
    server: DuckgresServer,
    username: str,
    password: str,
    reader_configured: bool,
) -> ExternalDataSource | None:
    # Deliberately includes soft-deleted rows: a re-enabled membership revives its tombstoned
    # source (the caller's credential pre-read filters deleted=False, so a revived row always
    # gets fresh credentials and stays disabled until the handshake completes).
    existing = _managed_source_queryset(team_id).select_for_update().order_by("-created_at").first()

    config = _source_config(server, username=username, password=password)
    if existing is not None:
        update_fields: list[str] = []
        connection_metadata = dict(existing.connection_metadata or {})
        if connection_metadata.get("credential_kind") != "project_reader":
            # Old managed sources used the org root credential, so discard any catalog
            # entries discovered before Duckgres enforced the project boundary.
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
        if existing.direct_query_enabled != reader_configured:
            existing.direct_query_enabled = reader_configured
            update_fields.append("direct_query_enabled")
        if (
            connection_metadata.get("engine") != "duckdb"
            or connection_metadata.get("system_managed") is not True
            or connection_metadata.get("credential_kind") != "project_reader"
        ):
            existing.connection_metadata = {
                **connection_metadata,
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "project_reader",
                "reader_configured": reader_configured,
            }
            update_fields.append("connection_metadata")
        elif connection_metadata.get("reader_configured") is not reader_configured:
            existing.connection_metadata = {**connection_metadata, "reader_configured": reader_configured}
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
        direct_query_enabled=reader_configured,
        connection_metadata={
            "engine": "duckdb",
            "system_managed": True,
            "credential_kind": "project_reader",
            "reader_configured": reader_configured,
        },
    )


def ensure_managed_warehouse_direct_source(*, team_id: int, organization_id: str | UUID) -> ExternalDataSource:
    """Create or refresh the team's restricted live-query source from its membership."""
    from posthog.ducklake.models import DuckgresServer, DuckgresServerTeam  # noqa: PLC0415

    with transaction.atomic():
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
        table_suffix = membership["table_suffix"]
        if not table_suffix:
            raise ValueError("Legacy shared managed warehouse tables cannot be exposed as a query connection")

        existing = _managed_source_queryset(team_id).select_for_update().filter(deleted=False).first()
        existing_metadata = existing.connection_metadata if existing is not None else None
        has_reader_credentials = (
            existing is not None
            and isinstance(existing_metadata, dict)
            and existing_metadata.get("credential_kind") == "project_reader"
            and isinstance(existing.job_inputs, dict)
            and existing.job_inputs.get("user")
            and existing.job_inputs.get("password")
        )
        if has_reader_credentials:
            assert existing is not None
            assert isinstance(existing_metadata, dict)
            assert isinstance(existing.job_inputs, dict)
            reader_configured = existing_metadata.get("reader_configured") is True
            username = str(existing.job_inputs["user"])
            password = str(existing.job_inputs["password"])
        else:
            reader_configured = False
            username = f"posthog_team_{team_id}"
            password = secrets.token_urlsafe(32)

        source = _ensure_managed_source_locked(
            team_id=team_id,
            server=server,
            username=username,
            password=password,
            reader_configured=reader_configured,
        )
        if source is None:
            raise RuntimeError("Failed to create the managed warehouse query source")
        if reader_configured:
            return source
        source_id = source.id

    credentials = managed_warehouse.configure_project_reader(
        organization_id=organization_id,
        team_id=team_id,
        table_suffix=table_suffix,
        password=password,
    )
    if credentials != {"username": username, "password": password}:
        raise RuntimeError("Managed warehouse reader credentials did not match the requested credentials")

    with transaction.atomic():
        server = DuckgresServer.objects.select_for_update().get(organization_id=organization_id)
        Team.objects.select_for_update().only("id").get(id=team_id, organization_id=organization_id)
        membership_exists = DuckgresServerTeam.objects.select_for_update().filter(
            server=server,
            team_id=team_id,
            backfill_enabled=True,
            table_suffix=table_suffix,
        )
        if not membership_exists.exists():
            raise ValueError("The team has not joined this managed warehouse")
        source = _managed_source_queryset(team_id).select_for_update().filter(id=source_id, deleted=False).first()
        if source is None or not isinstance(source.job_inputs, dict):
            raise RuntimeError("Managed warehouse query source changed while its reader was configured")
        if source.job_inputs.get("user") != username or source.job_inputs.get("password") != password:
            raise RuntimeError("Managed warehouse query source changed while its reader was configured")
        connection_metadata = dict(source.connection_metadata or {})
        source.connection_metadata = {**connection_metadata, "reader_configured": True}
        source.direct_query_enabled = True
        source.save(update_fields=["connection_metadata", "direct_query_enabled", "updated_at"])
        return source


def reconcile_managed_warehouse_tables(*, team_id: int, organization_id: str | UUID) -> None:
    """Discover and register only this team's managed-warehouse tables."""
    from posthog.ducklake.models import DuckgresServer, DuckgresServerTeam  # noqa: PLC0415

    try:
        ensure_managed_warehouse_direct_source(team_id=team_id, organization_id=organization_id)
    except (DuckgresServer.DoesNotExist, Team.DoesNotExist, ValueError):
        return
    except RuntimeError:
        # The credential handshake needs the warehouse control plane; while an org is still
        # provisioning this fails on every sweep, so skip quietly and let the next run retry.
        logger.info("Managed warehouse reader handshake not possible yet", team_id=team_id)
        return

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
        source = _managed_source_queryset(team_id).select_for_update().filter(deleted=False).first()
        if source is None:
            return
        source_id = source.id
        source_config = dict(source.job_inputs or {})
        source_api_version = source.api_version

    # The allowlist mirrors the live Duckgres org-team row (the same row its reader policy is
    # derived from), so hand-set layouts — legacy overrides like team 2's posthog.events, custom
    # schema names like devex — stay in sync instead of assuming the suffix-derived scheme.
    # Introspection also runs AS the reader, so this filter is defense in depth, not the boundary.
    namespaces = managed_warehouse.project_reader_namespaces(organization_id=organization_id, team_id=team_id)
    if namespaces is None:
        return
    allowed_schemas, allowed_relations = namespaces

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
    source_schemas = [
        schema
        for schema in discovered
        if (schema.source_schema or "", schema.source_table_name or schema.name.rsplit(".", 1)[-1]) in allowed_relations
        or (schema.source_schema or "") in allowed_schemas
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
                access_method=ExternalDataSource.AccessMethod.DIRECT,
                direct_query_enabled=True,
            )
            .first()
        )
        if membership is None or source is None:
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
    """Refresh the internal root writer without changing project reader credentials."""
    from posthog.ducklake.models import DuckgresServer  # noqa: PLC0415

    with transaction.atomic():
        server = DuckgresServer.objects.select_for_update().get(organization_id=organization_id)
        server.password = password
        server.save(update_fields=["password", "updated_at"])


def soft_delete_managed_warehouse_sources(*, organization_id: str | UUID) -> None:
    """Atomically tombstone the organization's managed query sources on deprovision."""
    from posthog.ducklake.models import DuckgresServer, DuckgresServerTeam  # noqa: PLC0415

    now = timezone.now()
    with transaction.atomic():
        DuckgresServer.objects.select_for_update().filter(organization_id=organization_id).first()
        sources = list(_managed_sources_for_org(organization_id).select_for_update().order_by("team_id"))
        DuckgresServerTeam.objects.filter(server__organization_id=organization_id).update(backfill_enabled=False)
        DataWarehouseTable.raw_objects.filter(
            external_data_source_id__in=[source.id for source in sources], deleted=False
        ).update(deleted=True, deleted_at=now, updated_at=now)
        for source in sources:
            source.deleted = True
            source.deleted_at = now
            source.save(update_fields=["deleted", "deleted_at", "updated_at"])
