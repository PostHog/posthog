import json
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.cleanup_property_definitions.activities import (
    delete_property_definitions_from_clickhouse,
    delete_property_definitions_from_postgres,
    preview_property_definitions,
)
from posthog.temporal.cleanup_property_definitions.types import (
    CleanupPropertyDefinitionsError,
    CleanupPropertyDefinitionsInput,
    DeleteClickHousePropertyDefinitionsInput,
    DeletePostgresPropertyDefinitionsInput,
    PreviewPropertyDefinitionsInput,
)
from posthog.temporal.common.base import PostHogWorkflow


@workflow.defn(name="cleanup-property-definitions")
class CleanupPropertyDefinitionsWorkflow(PostHogWorkflow):
    """Workflow to clean up person property definitions matching a regex pattern.

    This workflow deletes property definitions from both PostgreSQL and ClickHouse.
    It supports dry-run mode to preview what would be deleted.
    """

    @staticmethod
    def parse_inputs(input: list[str]) -> CleanupPropertyDefinitionsInput:
        """Parse input from the management command CLI."""
        loaded = json.loads(input[0])
        return CleanupPropertyDefinitionsInput(**loaded)

    @workflow.run
    async def run(self, input: CleanupPropertyDefinitionsInput) -> dict:
        """Run the cleanup workflow.

        Returns a dict with:
        - property_definitions_deleted: Number of definitions deleted from PostgreSQL
        - dry_run: Whether this was a dry run
        """
        property_type_int = input.get_property_type_int()

        result = {
            "team_id": input.team_id,
            "pattern": input.pattern,
            "property_type": input.property_type,
            "dry_run": input.dry_run,
            "property_definitions_deleted": 0,
            "event_properties_deleted": 0,
        }

        if input.dry_run:
            preview = await workflow.execute_activity(
                preview_property_definitions,
                PreviewPropertyDefinitionsInput(
                    team_id=input.team_id,
                    pattern=input.pattern,
                    property_type=property_type_int,
                ),
                start_to_close_timeout=timedelta(minutes=5),
            )
            result["preview"] = preview
            workflow.logger.info(
                f"DRY RUN: Would delete {preview['total_count']} {input.property_type} property definitions "
                f"matching pattern '{input.pattern}' for team {input.team_id}: {preview['names']}"
            )
            return result

        # Delete from PostgreSQL in batches to avoid long-held locks.
        # Each batch selects property names, then deletes from both
        # PropertyDefinition and EventProperty in a single transaction.
        batch_size = input.batch_size
        max_batches = 2_000_000 // batch_size
        total_property_definitions_deleted = 0
        total_event_properties_deleted = 0
        for _batch_num in range(max_batches + 1):
            postgres_result = await workflow.execute_activity(
                delete_property_definitions_from_postgres,
                DeletePostgresPropertyDefinitionsInput(
                    team_id=input.team_id,
                    pattern=input.pattern,
                    property_type=property_type_int,
                    batch_size=batch_size,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=common.RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=30),
                ),
            )
            batch_deleted = postgres_result["property_definitions_deleted"]
            total_property_definitions_deleted += batch_deleted
            total_event_properties_deleted += postgres_result["event_properties_deleted"]
            if batch_deleted < batch_size:
                break
            if _batch_num == max_batches:
                raise CleanupPropertyDefinitionsError(
                    f"Postgres delete exceeded {max_batches} batches "
                    f"({total_property_definitions_deleted:,} property definitions deleted). "
                    f"Re-run the workflow to continue deleting remaining rows."
                )
        result["property_definitions_deleted"] = total_property_definitions_deleted
        result["event_properties_deleted"] = total_event_properties_deleted

        # Delete from ClickHouse
        await workflow.execute_activity(
            delete_property_definitions_from_clickhouse,
            DeleteClickHousePropertyDefinitionsInput(
                team_id=input.team_id,
                pattern=input.pattern,
                property_type=property_type_int,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            schedule_to_close_timeout=timedelta(hours=1),
            retry_policy=common.RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=30),
            ),
        )

        workflow.logger.info(
            f"Cleanup complete: deleted {total_property_definitions_deleted} property definitions "
            f"and {total_event_properties_deleted} event properties from PostgreSQL, "
            f"and matching definitions from ClickHouse"
        )

        return result
