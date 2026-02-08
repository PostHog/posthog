from uuid import uuid4

from django.conf import settings

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

LOGGER = get_write_only_logger()


@activity.defn(name="delete-property-definitions-from-postgres")
async def delete_property_definitions_from_postgres(
    input: DeletePostgresPropertyDefinitionsInput,
) -> int:
    """Delete property definitions matching the pattern from PostgreSQL."""
    bind_contextvars(team_id=input.team_id, pattern=input.pattern, property_type=input.property_type)
    logger = LOGGER.bind()
    logger.info("Deleting property definitions from PostgreSQL")

    @database_sync_to_async
    def delete_definitions() -> int:
        # Validate team exists
        if not Team.objects.filter(id=input.team_id).exists():
            raise CleanupPropertyDefinitionsError(f"Team {input.team_id} not found")

        deleted_count, _ = PropertyDefinition.objects.filter(
            team_id=input.team_id,
            type=input.property_type,
            name__regex=input.pattern,
        ).delete()
        return deleted_count

    deleted_count = await delete_definitions()
    logger.info(f"Deleted {deleted_count} property definitions from PostgreSQL")
    return deleted_count


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
        if not Team.objects.filter(id=input.team_id).exists():
            raise CleanupPropertyDefinitionsError(f"Team {input.team_id} not found")

        queryset = PropertyDefinition.objects.filter(
            team_id=input.team_id,
            type=input.property_type,
            name__regex=input.pattern,
        )
        total_count = queryset.count()
        names = list(queryset.values_list("name", flat=True)[: input.limit])
        return {"total_count": total_count, "names": names, "truncated": total_count > input.limit}

    result = await get_matching_definitions()
    logger.info(f"Found {result['total_count']} matching property definitions")
    return result
