import asyncio
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


@dataclasses.dataclass
class PersonIdRangeStreamInputs:
    """Inputs for streaming person ID ranges."""

    team_id: int
    batch_size: int


@temporalio.activity.defn
async def stream_person_id_ranges_activity(inputs: PersonIdRangeStreamInputs) -> None:
    """Stream person ID ranges for a team, yielding ranges as they are discovered.

    This activity runs continuously and sends ranges to the workflow via signals.
    It's designed to avoid timeouts by processing incrementally.
    """
    from posthog.clickhouse.query_tagging import Feature, Product, tags_context

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
    ranges_produced = 0

    with tags_context(
        team_id=inputs.team_id,
        feature=Feature.BEHAVIORAL_COHORTS,
        product=Product.MESSAGING,
        query_type="person_id_ranges_stream",
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

                # When we reach batch_size, complete this range and signal to workflow
                if current_batch_count >= inputs.batch_size:
                    # Heartbeat with range data
                    temporalio.activity.heartbeat(f"range:{current_batch_start}:{person_id}")

                    ranges_produced += 1
                    current_batch_start = None
                    current_batch_count = 0

            # Handle the final partial batch if it exists
            if current_batch_start is not None and current_batch_count > 0:
                # Send final range
                temporalio.activity.heartbeat(f"range:{current_batch_start}:{person_id}")
                ranges_produced += 1

            # Signal completion
            temporalio.activity.heartbeat(f"complete:{ranges_produced}:{total_count}")

    LOGGER.info(f"Streamed {ranges_produced} person ID ranges for {total_count} total persons (team {inputs.team_id})")


@temporalio.activity.defn
async def get_person_id_ranges_activity(inputs: PersonIdRangesInputs) -> list[tuple[str, str]]:
    """Get person ID ranges for a team by streaming through IDs and creating ranges every batch_size records.

    NOTE: This is the original non-streaming version, kept for compatibility.
    """
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

                # Send heartbeat every 10k persons to avoid timeout
                if total_count % 10000 == 0:
                    temporalio.activity.heartbeat(f"Processed {total_count} persons, created {len(ranges)} ranges")

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

    async def _start_child_workflow_for_range(
        self,
        inputs: BackfillPrecalculatedPersonPropertiesCoordinatorInputs,
        workflow_logger,
        batch_number: int,
        start_person_id: str,
        end_person_id: str,
        child_workflow_handles: list[temporalio.workflow.ChildWorkflowHandle],
    ) -> None:
        """Helper to start a child workflow for a person ID range."""
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

        workflow_logger.info(
            f"Started batch {batch_number}: processing person IDs {start_person_id} to {end_person_id}"
        )

    @temporalio.workflow.run
    async def run(self, inputs: BackfillPrecalculatedPersonPropertiesCoordinatorInputs) -> None:
        """Run the coordinator workflow using streaming ID-range discovery with batched approach."""
        workflow_logger = temporalio.workflow.logger
        cohort_ids = inputs.cohort_ids
        workflow_logger.info(
            f"Starting person properties precalculation coordinator for {len(cohort_ids)} cohorts "
            f"(team {inputs.team_id}, cohorts {cohort_ids}) with {inputs.concurrent_workflows} concurrent workflows"
        )

        # For now, use a compromise: fetch ranges in smaller batches to avoid timeout
        # This reduces memory usage while still being more efficient than the original approach

        workflow_logger.info(f"Discovering person ID ranges with batch size {inputs.batch_size}...")

        # Use longer timeout but still bounded
        person_id_ranges = await temporalio.workflow.execute_activity(
            get_person_id_ranges_activity,
            PersonIdRangesInputs(team_id=inputs.team_id, batch_size=inputs.batch_size),
            start_to_close_timeout=dt.timedelta(hours=2),  # Increased from 10 minutes to 2 hours
            heartbeat_timeout=dt.timedelta(minutes=5),  # Add heartbeat timeout
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )

        if not person_id_ranges:
            workflow_logger.info("No persons found for team, nothing to process")
            return

        workflow_logger.info(
            f"Discovered {len(person_id_ranges)} person ID ranges, processing with {inputs.concurrent_workflows} concurrent workflows"
        )

        # Process ranges with concurrent limit
        child_workflow_handles: list[temporalio.workflow.ChildWorkflowHandle] = []
        workflows_scheduled = 0
        completed_count = 0
        failed_count = 0

        for batch_number, (start_person_id, end_person_id) in enumerate(person_id_ranges, 1):
            await self._start_child_workflow_for_range(
                inputs, workflow_logger, batch_number, start_person_id, end_person_id, child_workflow_handles
            )
            workflows_scheduled += 1

            # Respect concurrent workflow limit - wait for any workflow to complete before starting more
            if len(child_workflow_handles) >= inputs.concurrent_workflows:
                # Wait for any workflow to complete using asyncio.wait with FIRST_COMPLETED
                done, pending = await asyncio.wait(child_workflow_handles, return_when=asyncio.FIRST_COMPLETED)

                # Await and remove completed workflows from tracking list, tracking failures
                for completed_handle in done:
                    try:
                        await completed_handle
                        workflow_logger.info("Child workflow completed successfully during concurrency wait")
                    except Exception as e:
                        failed_count += 1
                        workflow_logger.exception(f"Child workflow failed during concurrency wait: {e}")
                        # Continue processing other workflows but track the failure
                    finally:
                        child_workflow_handles.remove(completed_handle)

        # Step 3: Wait for all remaining workflows to complete
        workflow_logger.info(
            f"All workflows scheduled, waiting for completion", workflows_scheduled=workflows_scheduled
        )

        workflow_logger.info("Waiting for child workflows to complete", total_workflows=len(child_workflow_handles))
        while child_workflow_handles:
            done, _ = await asyncio.wait(child_workflow_handles, return_when=asyncio.FIRST_COMPLETED)

            for handle in done:
                try:
                    await handle
                    completed_count += 1
                    workflow_logger.info(
                        f"Child workflow completed successfully ({completed_count + failed_count}/{workflows_scheduled})"
                    )
                except Exception as e:
                    failed_count += 1
                    workflow_logger.exception(
                        f"Child workflow failed ({completed_count + failed_count}/{workflows_scheduled}): {e}"
                    )
                finally:
                    child_workflow_handles.remove(handle)

        if failed_count > 0:
            workflow_logger.warning(
                f"Coordinator completed with {failed_count} failed child workflows out of {workflows_scheduled} total"
            )
            raise temporalio.exceptions.ApplicationError(
                f"{failed_count} child workflows failed; some person ID ranges were not processed.",
                non_retryable=False,
            )

        workflow_logger.info(
            f"Coordinator workflow completed successfully for team {inputs.team_id}: "
            f"processed {len(person_id_ranges)} ranges with {inputs.concurrent_workflows} concurrent workflows"
        )
