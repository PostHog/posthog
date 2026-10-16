from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import F, QuerySet

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.models import PropertyDefinition, Team
from posthog.sync import database_sync_to_async
from posthog.temporal.cleanup_property_definitions.types import (
    CleanupPropertyDefinitionsError,
    DeleteClickHousePropertyDefinitionsInput,
    DeletePostgresPropertyDefinitionsInput,
    PreviewPropertyDefinitionsInput,
)
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.logger import get_write_only_logger

from products.event_definitions.backend.models import effective_project_id_expr, group_type_index_key_expr
from products.event_definitions.backend.models.event_property import EventProperty

LOGGER = get_write_only_logger()


def _project_id_for_team(team_id: int) -> int:
    project_id = Team.objects.filter(id=team_id).values_list("project_id", flat=True).first()
    if project_id is None:
        raise CleanupPropertyDefinitionsError(f"Team {team_id} not found")
    return project_id


def _project_definitions(project_id: int, property_type: int) -> QuerySet[PropertyDefinition]:
    return PropertyDefinition.objects.alias(
        effective_project_id=effective_project_id_expr(),
        group_type_index_key=group_type_index_key_expr(),
    ).filter(effective_project_id=project_id, type=property_type)


def _definitions_matching(project_id: int, property_type: int, pattern: str) -> QuerySet[PropertyDefinition]:
    # The order is the key of index_property_def_query_proj, so Postgres reads that index in order and stops at
    # the slice limit. Without an order, Postgres plans a Seq Scan of the whole table for the largest projects.
    return (
        _project_definitions(project_id, property_type)
        .filter(name__regex=pattern)
        .order_by(
            "effective_project_id",
            "type",
            "group_type_index_key",
            F("query_usage_30_day").desc(nulls_last=True),
            "name",
        )
    )


@activity.defn(name="delete-property-definitions-from-postgres")
async def delete_property_definitions_from_postgres(
    input: DeletePostgresPropertyDefinitionsInput,
) -> dict:
    """Delete up to batch_size property definitions matching the pattern from PostgreSQL.

    Selects a batch of matching property names, then deletes from both
    PropertyDefinition and EventProperty using those names
    in a single transaction. The workflow calls this in a loop until
    property_definitions_deleted < batch_size.
    """
    bind_contextvars(team_id=input.team_id, pattern=input.pattern, property_type=input.property_type)
    logger = LOGGER.bind()
    logger.info("Deleting property definitions from PostgreSQL", batch_size=input.batch_size)

    @database_sync_to_async
    def delete_batch() -> dict:
        project_id = _project_id_for_team(input.team_id)

        # Select a batch of matching property names to coordinate deletes across tables
        batch_names = list(
            _definitions_matching(project_id, input.property_type, input.pattern).values_list("name", flat=True)[
                : input.batch_size
            ]
        )
        if not batch_names:
            return {"property_definitions_deleted": 0, "event_properties_deleted": 0}

        with transaction.atomic():
            property_definitions_deleted, _ = (
                _project_definitions(project_id, input.property_type).filter(name__in=batch_names).delete()
            )

            event_properties_deleted, _ = EventProperty.objects.filter(
                team_id=input.team_id,
                property__in=batch_names,
            ).delete()

        return {
            "property_definitions_deleted": property_definitions_deleted,
            "event_properties_deleted": event_properties_deleted,
        }

    result = await delete_batch()
    logger.info(
        f"Deleted {result['property_definitions_deleted']} property definitions "
        f"and {result['event_properties_deleted']} event properties from PostgreSQL"
    )
    return result


@activity.defn(name="delete-property-definitions-from-clickhouse")
async def delete_property_definitions_from_clickhouse(
    input: DeleteClickHousePropertyDefinitionsInput,
) -> None:
    """Delete property definitions matching the pattern from ClickHouse using lightweight delete."""
    bind_contextvars(team_id=input.team_id, pattern=input.pattern, property_type=input.property_type)
    logger = LOGGER.bind()
    logger.info("Deleting property definitions from ClickHouse")

    # Use lightweight delete (DELETE FROM syntax)
    # Data is marked as deleted immediately (not visible in queries)
    # Actual disk cleanup happens asynchronously during regular OPTIMIZE TABLE FINAL
    delete_query = """
        DELETE FROM property_definitions
        WHERE team_id = %(team_id)s
          AND type = %(property_type)s
          AND match(name, %(pattern)s)
    """

    delete_query_id = str(uuid4())
    logger.info(f"Executing lightweight delete with query_id: {delete_query_id}")

    # In production, use lightweight_deletes_sync=0 to avoid waiting for all replicas.
    # In tests, use lightweight_deletes_sync=2 to ensure deletes are visible immediately.
    lightweight_deletes_sync = 2 if settings.TEST else 0

    async with get_client(lightweight_deletes_sync=lightweight_deletes_sync) as client:
        await client.execute_query(
            delete_query,
            query_parameters={
                "team_id": input.team_id,
                "pattern": input.pattern,
                "property_type": input.property_type,
            },
            query_id=delete_query_id,
        )

    logger.info("Deleted matching property definitions from ClickHouse")


@activity.defn(name="preview-property-definitions")
async def preview_property_definitions(input: PreviewPropertyDefinitionsInput) -> dict:
    """Preview property definitions that would be deleted."""
    bind_contextvars(team_id=input.team_id, pattern=input.pattern, property_type=input.property_type)
    logger = LOGGER.bind()
    logger.info("Previewing property definitions for deletion")

    @database_sync_to_async
    def get_matching_definitions() -> dict:
        project_id = _project_id_for_team(input.team_id)

        queryset = _definitions_matching(project_id, input.property_type, input.pattern)
        total_count = queryset.count()
        names = list(queryset.values_list("name", flat=True)[: input.limit])
        return {"total_count": total_count, "names": names, "truncated": total_count > input.limit}

    result = await get_matching_definitions()
    logger.info(f"Found {result['total_count']} matching property definitions")
    return result
