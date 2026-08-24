from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction

import psycopg
from asgiref.sync import async_to_sync

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.logger import get_logger

from products.data_modeling.backend.facade import api as data_modeling
from products.managed_warehouse.backend.facade import api as managed_warehouse
from products.managed_warehouse.backend.facade.client import execute_ducklake_query
from products.managed_warehouse.backend.facade.contracts import (
    CPUnavailableError,
    ManagedWarehouseModeledTable,
    ManagedWarehousePublishedTableRecord,
)
from products.managed_warehouse.backend.facade.temporal import PrunePublishedSnapshotInputs, PublishTableInputs
from products.warehouse_sources.backend.facade import api as warehouse_sources

LOGGER = get_logger(__name__)

_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_DISCOVERY_CONNECT_TIMEOUT_SECONDS = 5
_DISCOVERY_STATEMENT_TIMEOUT_SECONDS = 5

_WAREHOUSE_TABLES_SQL = """
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_type = 'BASE TABLE'
ORDER BY table_schema, table_name
"""


class PublishValidationError(Exception):
    pass


class ModeledTableDiscoveryError(Exception):
    pass


def list_modeled_tables(team_id: int) -> list[ManagedWarehouseModeledTable]:
    if not managed_warehouse.is_dev_mode() and not managed_warehouse.has_provisioned_warehouse(
        managed_warehouse.get_org_id_for_team(team_id)
    ):
        return []

    try:
        result = execute_ducklake_query(
            team_id,
            sql=_WAREHOUSE_TABLES_SQL,
            connect_timeout_seconds=_DISCOVERY_CONNECT_TIMEOUT_SECONDS,
            statement_timeout_seconds=_DISCOVERY_STATEMENT_TIMEOUT_SECONDS,
        )
    except (CPUnavailableError, psycopg.Error) as error:
        raise ModeledTableDiscoveryError("The managed warehouse is temporarily unavailable.") from error
    tables: list[ManagedWarehouseModeledTable] = []
    for row in result.results:
        schema_name = str(row[0])
        table_name = str(row[1])
        disabled_reason = managed_warehouse.table_publish_block_reason(
            schema_name, table_name, reserved_table_names=frozenset()
        )
        tables.append(
            ManagedWarehouseModeledTable(
                schema_name=schema_name,
                table_name=table_name,
                publishable=disabled_reason is None,
                disabled_reason=disabled_reason,
            )
        )
    return tables


def create_publication(
    *,
    team: Team,
    source_schema_name: str,
    source_table_name: str,
    name: str | None,
    created_by_id: int | None = None,
) -> ManagedWarehousePublishedTableRecord:
    canonical_team = team.parent_team or team
    if (
        not managed_warehouse.has_provisioned_warehouse(canonical_team.organization_id)
        and not managed_warehouse.is_dev_mode()
    ):
        raise PublishValidationError("No managed warehouse is provisioned for this organization.")

    try:
        managed_warehouse.validate_duckgres_identifier(source_schema_name)
        managed_warehouse.validate_duckgres_identifier(source_table_name)
    except ValueError as error:
        raise PublishValidationError(str(error)) from error

    disabled_reason = managed_warehouse.table_publish_block_reason(
        source_schema_name,
        source_table_name,
        reserved_table_names=frozenset(),
    )
    if disabled_reason is not None:
        raise PublishValidationError(disabled_reason)

    resolved_name = name or managed_warehouse.sanitize_ducklake_identifier(
        f"{source_schema_name}_{source_table_name}", default_prefix="published"
    )
    if not _NAME_PATTERN.match(resolved_name) or len(resolved_name) > 128:
        raise PublishValidationError(
            "Table name must start with a letter or underscore, use only letters, numbers, and "
            "underscores, and be at most 128 characters."
        )

    name_taken = (
        warehouse_sources.active_table_name_exists(team_id=canonical_team.pk, name=resolved_name)
        or data_modeling.active_saved_query_name_exists(team_id=canonical_team.pk, name=resolved_name)
        or managed_warehouse.managed_warehouse_published_table_name_exists(canonical_team.pk, resolved_name)
    )
    if name_taken:
        raise PublishValidationError(f"A warehouse table named '{resolved_name}' already exists.")

    try:
        with transaction.atomic():
            saved_query = data_modeling.create_managed_warehouse_saved_query(
                team_id=canonical_team.pk,
                name=resolved_name,
                source_schema_name=source_schema_name,
                source_table_name=source_table_name,
                created_by_id=created_by_id,
            )
            return managed_warehouse.create_managed_warehouse_published_table(
                team_id=canonical_team.pk,
                source_schema_name=source_schema_name,
                source_table_name=source_table_name,
                name=resolved_name,
                saved_query_id=saved_query.id,
                created_by_id=created_by_id,
            )
    except IntegrityError as error:
        raise PublishValidationError(f"A warehouse table named '{resolved_name}' already exists.") from error


def _start_workflow(
    workflow_name: str,
    workflow_id: str,
    inputs: PublishTableInputs | PrunePublishedSnapshotInputs,
) -> None:
    temporal = sync_connect()
    start_workflow = cast(Callable[..., Any], async_to_sync(temporal.start_workflow))
    start_workflow(
        workflow_name,
        inputs,
        id=workflow_id,
        task_queue=str(settings.DUCKLAKE_TASK_QUEUE),
    )


def list_publications(team_id: int) -> list[ManagedWarehousePublishedTableRecord]:
    return managed_warehouse.list_managed_warehouse_published_tables(team_id)


def get_publication(team_id: int, publication_id: UUID | str) -> ManagedWarehousePublishedTableRecord | None:
    publication = managed_warehouse.get_managed_warehouse_published_table(team_id, publication_id)
    return publication if publication is not None and not publication.deleted else None


def start_publish_workflow(publication: ManagedWarehousePublishedTableRecord) -> None:
    inputs = PublishTableInputs(team_id=publication.team_id, publication_id=str(publication.id))
    _start_workflow("duckgres-publish-table", f"duckgres-publish-{publication.id}", inputs)


def start_snapshot_prune_workflow(publication: ManagedWarehousePublishedTableRecord) -> None:
    inputs = PrunePublishedSnapshotInputs(team_id=publication.team_id, publication_id=str(publication.id))
    _start_workflow("duckgres-prune-published-snapshot", f"duckgres-prune-published-{publication.id}", inputs)


def delete_publication(publication: ManagedWarehousePublishedTableRecord) -> None:
    with transaction.atomic():
        if publication.table_id is not None:
            warehouse_sources.soft_delete_table_if_exists(team_id=publication.team_id, table_id=publication.table_id)

        managed_warehouse.mark_managed_warehouse_published_table_deleted(publication.team_id, publication.id)
        if publication.saved_query_id is not None:
            data_modeling.delete_managed_warehouse_saved_query(publication.team_id, publication.saved_query_id)

        # The parquet snapshot in the org bucket must go too, but only the temporal
        # workers hold the cross-account DeleteObject grant — schedule the prune and
        # let a failed schedule surface in Sentry rather than break the delete.
        transaction.on_commit(lambda: _start_snapshot_prune_best_effort(publication))


def _start_snapshot_prune_best_effort(publication: ManagedWarehousePublishedTableRecord) -> None:
    try:
        start_snapshot_prune_workflow(publication)
    except Exception as error:
        LOGGER.exception("snapshot_prune_schedule_failed", publication_id=str(publication.id))
        capture_exception(error)
