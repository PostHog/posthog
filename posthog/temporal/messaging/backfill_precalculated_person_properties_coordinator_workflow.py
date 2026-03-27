import dataclasses
from typing import Any

from django.conf import settings

import temporalio.common
import temporalio.workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.messaging.backfill_precalculated_person_properties_workflow import (
    BackfillPrecalculatedPersonPropertiesInputs,
    BackfillPrecalculatedPersonPropertiesResult,
)

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class BackfillPrecalculatedPersonPropertiesCoordinatorInputs:
    """Inputs for the coordinator workflow using cursor-based pagination."""

    team_id: int
    filter_storage_key: str  # Redis key containing the filters
    cohort_ids: list[int]  # All cohort IDs being processed
    batch_size: int = 1000  # Persons per batch

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "cohort_count": len(self.cohort_ids),
            "cohort_ids": self.cohort_ids,
            "filter_storage_key": self.filter_storage_key,
            "batch_size": self.batch_size,
        }


@temporalio.workflow.defn(name="backfill-precalculated-person-properties-coordinator")
class BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow(PostHogWorkflow):
    """Coordinator workflow that processes persons sequentially using cursor-based pagination.

    Uses cursor-based pagination to avoid O(n²) performance issues with large datasets.
    Spawns child workflows batch by batch, waiting for each to complete before starting
    the next batch. Each batch processes a range of persons starting from the cursor.

    Child workflow ID format: {coordinator_workflow_id}-batch-{batch_number}
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BackfillPrecalculatedPersonPropertiesCoordinatorInputs:
        """Parse inputs from the management command CLI."""
        raise NotImplementedError("Use start_workflow() to trigger this workflow programmatically")

    @temporalio.workflow.run
    async def run(self, inputs: BackfillPrecalculatedPersonPropertiesCoordinatorInputs) -> None:
        """Run the coordinator workflow using cursor-based pagination."""
        workflow_logger = temporalio.workflow.logger
        cohort_ids = inputs.cohort_ids
        workflow_logger.info(
            f"Starting person properties precalculation coordinator for {len(cohort_ids)} cohorts "
            f"(team {inputs.team_id}, cohorts {cohort_ids}) using cursor-based pagination"
        )

        workflow_logger.info(f"Processing cohorts: {cohort_ids}")

        # Start with the minimum UUID cursor
        current_cursor = "00000000-0000-0000-0000-000000000000"
        total_processed = 0
        batch_number = 0

        while True:
            batch_number += 1
            workflow_logger.info(
                f"Starting batch {batch_number} from cursor {current_cursor}, "
                f"processed {total_processed} persons so far"
            )

            # Spawn a child workflow to process the next batch
            child_workflow_id = f"{temporalio.workflow.info().workflow_id}-batch-{batch_number}"
            child_inputs = BackfillPrecalculatedPersonPropertiesInputs(
                team_id=inputs.team_id,
                filter_storage_key=inputs.filter_storage_key,
                cohort_ids=inputs.cohort_ids,
                batch_size=inputs.batch_size,
                cursor=current_cursor,
            )

            try:
                # Start and wait for the child workflow to complete
                raw_result = await temporalio.workflow.execute_child_workflow(
                    "backfill-precalculated-person-properties",
                    child_inputs,
                    id=child_workflow_id,
                    task_queue=settings.MESSAGING_TASK_QUEUE,
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                )

                # Handle potential dictionary result from Temporal serialization
                if isinstance(raw_result, dict):
                    result = BackfillPrecalculatedPersonPropertiesResult(**raw_result)
                else:
                    result = raw_result

                workflow_logger.info(
                    f"Batch {batch_number} completed: processed {result.persons_processed} persons, "
                    f"last_person_id: {result.last_person_id}"
                )

                # If no persons were processed, we're done
                if result.persons_processed == 0:
                    workflow_logger.info(f"No more persons to process. Completed after {total_processed} persons.")
                    break

                # If we processed fewer persons than the batch size, we've reached the end
                if result.persons_processed < inputs.batch_size:
                    total_processed += result.persons_processed
                    workflow_logger.info(
                        f"Reached end of data: processed {result.persons_processed} < {inputs.batch_size} batch size. Completed after {total_processed} total persons."
                    )
                    break

                # Update cursor for next batch
                if result.last_person_id:
                    current_cursor = result.last_person_id
                    total_processed += result.persons_processed
                else:
                    # This shouldn't happen if persons_processed > 0, but handle it safely
                    workflow_logger.warning("No last_person_id returned despite processing persons. Stopping.")
                    break

            except Exception as e:
                workflow_logger.error(f"Batch {batch_number} failed: {e}", exc_info=True)
                raise

        workflow_logger.info(
            f"Coordinator workflow completed successfully for team {inputs.team_id} "
            f"with {len(inputs.cohort_ids)} cohorts {inputs.cohort_ids}. "
            f"Total persons processed: {total_processed}"
        )
