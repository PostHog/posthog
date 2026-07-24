from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, cast

from django.conf import settings
from django.db import IntegrityError, transaction

import psycopg
from asgiref.sync import async_to_sync

from posthog.ducklake.client import execute_ducklake_query
from posthog.ducklake.common import (
    get_duckgres_server_by_team_org,
    is_dev_mode,
    sanitize_ducklake_identifier,
    validate_duckgres_identifier,
)
from posthog.ducklake.models import DuckgresServerTeam, ManagedWarehousePublishedTable
from posthog.ducklake.publish import ModeledTable, is_publishable_table, reserved_backfill_table_names
from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.logger import get_logger
from posthog.temporal.ducklake.publish_table_workflow import PrunePublishedSnapshotInputs, PublishTableInputs

from products.warehouse_sources.backend.facade.models import DataWarehouseTable

LOGGER = get_logger(__name__)

_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_DISCOVERY_CONNECT_TIMEOUT_SECONDS = 5
_DISCOVERY_STATEMENT_TIMEOUT_SECONDS = 5

_MODELED_TABLES_SQL = """
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_type = 'BASE TABLE'
ORDER BY table_schema, table_name
"""


class PublishValidationError(Exception):
    pass


class ModeledTableDiscoveryError(Exception):
    pass


def list_modeled_tables(team_id: int) -> list[ModeledTable]:
    if get_duckgres_server_by_team_org(team_id) is None and not is_dev_mode():
        return []

    table_suffix = DuckgresServerTeam.objects.filter(team_id=team_id).values_list("table_suffix", flat=True).first()
    reserved_table_names = reserved_backfill_table_names(table_suffix)
    try:
        result = execute_ducklake_query(
            team_id,
            sql=_MODELED_TABLES_SQL,
            connect_timeout_seconds=_DISCOVERY_CONNECT_TIMEOUT_SECONDS,
            statement_timeout_seconds=_DISCOVERY_STATEMENT_TIMEOUT_SECONDS,
        )
    except psycopg.Error as error:
        raise ModeledTableDiscoveryError("The managed warehouse is temporarily unavailable.") from error
    return [
        ModeledTable(schema_name=str(row[0]), table_name=str(row[1]))
        for row in result.results
        if is_publishable_table(str(row[0]), str(row[1]), reserved_table_names=reserved_table_names)
    ]


def create_publication(
    *,
    team: Team,
    source_schema_name: str,
    source_table_name: str,
    name: str | None,
) -> ManagedWarehousePublishedTable:
    if get_duckgres_server_by_team_org(team.pk) is None and not is_dev_mode():
        raise PublishValidationError("No managed warehouse is provisioned for this organization.")

    try:
        validate_duckgres_identifier(source_schema_name)
        validate_duckgres_identifier(source_table_name)
    except ValueError as error:
        raise PublishValidationError(str(error)) from error

    resolved_name = name or sanitize_ducklake_identifier(
        f"{source_schema_name}_{source_table_name}", default_prefix="published"
    )
    if not _NAME_PATTERN.match(resolved_name) or len(resolved_name) > 128:
        raise PublishValidationError(
            "Table name must start with a letter or underscore, use only letters, numbers, and "
            "underscores, and be at most 128 characters."
        )

    name_taken = (
        DataWarehouseTable.objects.filter(team_id=team.pk, name=resolved_name).exclude(deleted=True).exists()
        or ManagedWarehousePublishedTable.objects.for_team(team.pk).filter(name=resolved_name, deleted=False).exists()
    )
    if name_taken:
        raise PublishValidationError(f"A warehouse table named '{resolved_name}' already exists.")

    try:
        with transaction.atomic():
            return ManagedWarehousePublishedTable.objects.for_team(team.pk).create(
                team=team,
                source_schema_name=source_schema_name,
                source_table_name=source_table_name,
                name=resolved_name,
            )
    except IntegrityError as error:
        raise PublishValidationError(f"A warehouse table named '{resolved_name}' already exists.") from error


def start_publish_workflow(publication: ManagedWarehousePublishedTable) -> None:
    temporal = sync_connect()
    inputs = PublishTableInputs(team_id=publication.team_id, publication_id=str(publication.id))
    start_workflow = cast(Callable[..., Any], async_to_sync(temporal.start_workflow))
    start_workflow(
        "duckgres-publish-table",
        inputs,
        id=f"duckgres-publish-{publication.id}",
        task_queue=str(settings.DUCKLAKE_TASK_QUEUE),
    )


def start_snapshot_prune_workflow(publication: ManagedWarehousePublishedTable) -> None:
    temporal = sync_connect()
    inputs = PrunePublishedSnapshotInputs(team_id=publication.team_id, publication_id=str(publication.id))
    start_workflow = cast(Callable[..., Any], async_to_sync(temporal.start_workflow))
    start_workflow(
        "duckgres-prune-published-snapshot",
        inputs,
        id=f"duckgres-prune-published-{publication.id}",
        task_queue=str(settings.DUCKLAKE_TASK_QUEUE),
    )


def delete_publication(publication: ManagedWarehousePublishedTable) -> None:
    with transaction.atomic():
        if publication.table_id is not None:
            table = DataWarehouseTable.objects.filter(team_id=publication.team_id, id=publication.table_id).first()
            if table is not None:
                table.soft_delete()

        publication.deleted = True
        publication.save(update_fields=["deleted", "updated_at"])

        # The parquet snapshot in the org bucket must go too, but only the temporal
        # workers hold the cross-account DeleteObject grant — schedule the prune and
        # let a failed schedule surface in Sentry rather than break the delete.
        transaction.on_commit(lambda: _start_snapshot_prune_best_effort(publication))


def _start_snapshot_prune_best_effort(publication: ManagedWarehousePublishedTable) -> None:
    try:
        start_snapshot_prune_workflow(publication)
    except Exception as error:
        LOGGER.exception("snapshot_prune_schedule_failed", publication_id=str(publication.id))
        capture_exception(error)
