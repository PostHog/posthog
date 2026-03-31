import datetime as dt
import dataclasses
from typing import Any

from django.conf import settings

import temporalio.common
import temporalio.activity
import temporalio.workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.logger import get_logger
from posthog.temporal.messaging.backfill_precalculated_person_properties_workflow import (
    BackfillPrecalculatedPersonPropertiesInputs,
)

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class PersonIdRangesInputs:
    """Inputs for getting person ID ranges."""

    team_id: int
    batch_size: int


@temporalio.activity.defn
async def get_person_id_ranges_activity(inputs: PersonIdRangesInputs) -> list[tuple[str, str]]:
    """Get person ID ranges for a team by streaming through IDs and creating ranges every batch_size records."""
    from posthog.clickhouse.query_tagging import Feature, Product, tags_context

    ranges = []
    query = """
        SELECT id as person_id
        FROM person FINAL
        WHERE team_id = %(team_id)s
          AND is_deleted = 0
        ORDER BY id
        FORMAT JSONEachRow
    """

    current_batch_start = None
    current_batch_count = 0
    total_count = 0

    with tags_context(
        team_id=inputs.team_id,
        feature=Feature.BEHAVIORAL_COHORTS,
        product=Product.MESSAGING,
        query_type="person_id_ranges_fetch",
    ):
        async with get_client(team_id=inputs.team_id) as client:
            async for row in client.stream_query_as_jsonl(query, query_parameters={"team_id": inputs.team_id}):
                person_id = str(row["person_id"])

                # Start of first batch or new batch
                if current_batch_start is None:
                    current_batch_start = person_id
                    current_batch_count = 1
                else:
                    current_batch_count += 1

                total_count += 1

                # When we reach batch_size, complete this range and start a new one
                if current_batch_count >= inputs.batch_size:
                    ranges.append((current_batch_start, person_id))
                    current_batch_start = None
                    current_batch_count = 0

            # Handle the final partial batch if it exists
            if current_batch_start is not None and current_batch_count > 0:
                ranges.append((current_batch_start, person_id))

    LOGGER.info(f"Created {len(ranges)} person ID ranges for {total_count} total persons (team {inputs.team_id})")
    return ranges


@dataclasses.dataclass
class BackfillPrecalculatedPersonPropertiesCoordinatorInputs:
    """Inputs for the coordinator workflow using ID-range based batching."""

    team_id: int
    filter_storage_key: str  # Redis key containing the filters
    cohort_ids: list[int]  # All cohort IDs being processed
    batch_size: int = 1000  # Persons per batch
    concurrent_workflows: int = 5  # Number of concurrent workflows to run

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "cohort_count": len(self.cohort_ids),
            "cohort_ids": self.cohort_ids,
            "filter_storage_key": self.filter_storage_key,
            "batch_size": self.batch_size,
            "concurrent_workflows": self.concurrent_workflows,
        }


@temporalio.workflow.defn(name="backfill-precalculated-person-properties-coordinator")
class BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow(PostHogWorkflow):
    """Coordinator workflow that processes persons using ID-range based batching.

    First fetches all person IDs for the team, then splits them into ranges
    and processes multiple ranges concurrently using child workflows.
    This approach provides better parallelism and predictable batch sizes.

    Child workflow ID format: {coordinator_workflow_id}-batch-{batch_number}
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BackfillPrecalculatedPersonPropertiesCoordinatorInputs:
        """Parse inputs from the management command CLI."""
        raise NotImplementedError("Use start_workflow() to trigger this workflow programmatically")

    @temporalio.workflow.run
    async def run(self, inputs: BackfillPrecalculatedPersonPropertiesCoordinatorInputs) -> None:
        """Run the coordinator workflow using ID-range based batching."""
        workflow_logger = temporalio.workflow.logger
        cohort_ids = inputs.cohort_ids
        workflow_logger.info(
            f"Starting person properties precalculation coordinator for {len(cohort_ids)} cohorts "
            f"(team {inputs.team_id}, cohorts {cohort_ids}) with {inputs.concurrent_workflows} concurrent workflows"
        )

        # Step 1: Get person ID ranges for the team
        workflow_logger.info(f"Creating person ID ranges with batch size {inputs.batch_size}...")
        person_id_ranges = await temporalio.workflow.execute_activity(
            get_person_id_ranges_activity,
            PersonIdRangesInputs(team_id=inputs.team_id, batch_size=inputs.batch_size),
            start_to_close_timeout=dt.timedelta(minutes=10),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )

        if not person_id_ranges:
            workflow_logger.info("No persons found for team, nothing to process")
            return

        workflow_logger.info(
            f"Created {len(person_id_ranges)} person ID ranges, will process with {inputs.concurrent_workflows} concurrent workflows"
        )

        # Step 2: Start workflows in batches with concurrent limit, like realtime cohorts
        child_workflow_handles = []
        workflows_scheduled = 0

        for batch_number, (start_person_id, end_person_id) in enumerate(person_id_ranges, 1):
            child_workflow_id = f"{temporalio.workflow.info().workflow_id}-batch-{batch_number}"
            child_inputs = BackfillPrecalculatedPersonPropertiesInputs(
                team_id=inputs.team_id,
                filter_storage_key=inputs.filter_storage_key,
                cohort_ids=inputs.cohort_ids,
                batch_size=inputs.batch_size,
                start_person_id=start_person_id,
                end_person_id=end_person_id,
            )

            # Start child workflow
            child_handle = await temporalio.workflow.start_child_workflow(
                "backfill-precalculated-person-properties",
                child_inputs,
                id=child_workflow_id,
                task_queue=settings.MESSAGING_TASK_QUEUE,
                parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
            )
            child_workflow_handles.append(child_handle)
            workflows_scheduled += 1

            workflow_logger.info(
                f"Started batch {batch_number}: processing person IDs {start_person_id} to {end_person_id}"
            )

            # Respect concurrent workflow limit - wait for oldest to complete before starting more
            if len(child_workflow_handles) >= inputs.concurrent_workflows:
                # Wait for the oldest workflow to complete
                oldest_handle = child_workflow_handles.pop(0)
                await oldest_handle
                workflow_logger.info(f"Workflow completed, {len(child_workflow_handles)} still running")

        # Step 3: Wait for all remaining workflows to complete
        workflow_logger.info(
            f"All workflows scheduled, waiting for completion", workflows_scheduled=workflows_scheduled
        )

        completed_count = 0
        failed_count = 0

        workflow_logger.info("Waiting for child workflows to complete", total_workflows=len(child_workflow_handles))
        for handle in child_workflow_handles:
            try:
                await handle
                completed_count += 1
                workflow_logger.info(
                    f"Child workflow completed successfully ({completed_count + failed_count}/{len(child_workflow_handles)})"
                )
            except Exception as e:
                failed_count += 1
                workflow_logger.exception(
                    f"Child workflow failed ({completed_count + failed_count}/{len(child_workflow_handles)}): {e}"
                )

        if failed_count > 0:
            workflow_logger.warning(
                f"Coordinator completed with {failed_count} failed child workflows out of {len(child_workflow_handles)} total"
            )

        workflow_logger.info(
            f"Coordinator workflow completed successfully for team {inputs.team_id}: "
            f"processed {len(person_id_ranges)} ranges with {inputs.concurrent_workflows} concurrent workflows"
        )
