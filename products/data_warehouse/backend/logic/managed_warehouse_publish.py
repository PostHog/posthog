from __future__ import annotations

import re

from django.conf import settings
from django.db import transaction

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
from posthog.models.team.team import Team
from posthog.temporal.common.client import sync_connect
from posthog.temporal.ducklake.publish_table_workflow import PublishTableInputs

from products.warehouse_sources.backend.facade.models import DataWarehouseTable

_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

_MODELED_TABLES_SQL = """
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_type = 'BASE TABLE'
ORDER BY table_schema, table_name
"""


class PublishValidationError(Exception):
    pass


def list_modeled_tables(team_id: int) -> list[ModeledTable]:
    table_suffix = DuckgresServerTeam.objects.filter(team_id=team_id).values_list("table_suffix", flat=True).first()
    reserved_table_names = reserved_backfill_table_names(table_suffix)
    result = execute_ducklake_query(team_id, sql=_MODELED_TABLES_SQL)
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

    return ManagedWarehousePublishedTable.objects.for_team(team.pk).create(
        team=team,
        source_schema_name=source_schema_name,
        source_table_name=source_table_name,
        name=resolved_name,
    )


def start_publish_workflow(publication: ManagedWarehousePublishedTable) -> None:
    temporal = sync_connect()
    inputs = PublishTableInputs(team_id=publication.team_id, publication_id=str(publication.id))
    async_to_sync(temporal.start_workflow)(
        "duckgres-publish-table",
        inputs,
        id=f"duckgres-publish-{publication.id}",
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
