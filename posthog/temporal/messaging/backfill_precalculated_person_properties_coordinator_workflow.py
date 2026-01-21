import json
import math
import datetime as dt
import dataclasses
from typing import Any, TypedDict

from django.conf import settings

import temporalio.common
import temporalio.activity
import temporalio.workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.logger import get_logger
from posthog.temporal.messaging.backfill_precalculated_person_properties_workflow import (
    BackfillPrecalculatedPersonPropertiesInputs,
    BackfillPrecalculatedPersonPropertiesWorkflow,
    PersonPropertyFilter,
)

LOGGER = get_logger(__name__)

# Constants for UUID sampling
PERSON_ID_SAMPLE_RATE = 0.01  # Sample 1% of person IDs to find partition boundaries
SAMPLE_RATE_MULTIPLIER = 100  # Multiplier to estimate total from sample (inverse of sample rate)


class ChildWorkflowConfig(TypedDict):
    """Type definition for child workflow configuration."""

    id: str
    inputs: BackfillPrecalculatedPersonPropertiesInputs
    index: int


@dataclasses.dataclass
class BackfillPrecalculatedPersonPropertiesCoordinatorInputs:
    """Inputs for the coordinator workflow that spawns child workflows."""

    team_id: int
    filters: list[PersonPropertyFilter]  # Deduplicated person property filters
    parallelism: int = 10  # Number of child workflows to spawn
    batch_size: int = 1000  # Persons per batch within each worker
    workflows_per_batch: int = 5  # Number of workflows to start per batch
    batch_delay_minutes: int = 5  # Delay between batches in minutes

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "filter_count": len(self.filters),
            "parallelism": self.parallelism,
            "batch_size": self.batch_size,
            "workflows_per_batch": self.workflows_per_batch,
            "batch_delay_minutes": self.batch_delay_minutes,
        }


@dataclasses.dataclass
class UUIDBoundariesResult:
    """Result from sampling UUID boundaries for partitioning."""

    boundaries: list[str]  # List of UUID strings representing partition boundaries
    total_persons: int  # Total number of persons for logging


@temporalio.activity.defn
async def sample_uuid_boundaries_activity(
    inputs: BackfillPrecalculatedPersonPropertiesCoordinatorInputs,
) -> UUIDBoundariesResult:
    """Sample UUID boundaries to partition persons evenly across workers.

    Uses random sampling (approximately 1% of person IDs) to find percentile boundaries.
    Returns parallelism-1 boundaries that divide the UUID space into parallelism partitions.
    """
    parallelism = inputs.parallelism

    # Query to sample person IDs and get total count
    # First get total count, then sample using ORDER BY rand() LIMIT for engines that don't support SAMPLE
    count_query = """
        SELECT count() as total_count
        FROM (
            SELECT id
            FROM person
            WHERE team_id = %(team_id)s
            GROUP BY id
            HAVING max(is_deleted) = 0
        )
        FORMAT JSONEachRow
    """

    query_params = {"team_id": inputs.team_id}

    # Get total count first
    total_count = 0
    async with get_client(team_id=inputs.team_id) as client:
        response = await client.read_query(count_query, query_parameters=query_params)
        for line in response.decode("utf-8").splitlines():
            if line.strip():
                try:
                    row = json.loads(line)
                    total_count = int(row["total_count"])
                    break
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    LOGGER.exception("Failed to parse count result", line=line, error=str(e))
                    raise

    if total_count == 0:
        # No persons found, return empty boundaries
        return UUIDBoundariesResult(boundaries=[], total_persons=0)

    # Calculate sample size (1% of total, minimum 100, maximum 100k)
    sample_size = max(100, min(int(total_count * PERSON_ID_SAMPLE_RATE), 100_000))

    # Query to sample person IDs using ORDER BY rand() LIMIT (works on all engines)
    query = """
        SELECT groupArray(id) as sampled_ids
        FROM (
            SELECT id
            FROM person
            WHERE team_id = %(team_id)s
            GROUP BY id
            HAVING max(is_deleted) = 0
            ORDER BY rand()
            LIMIT %(sample_size)s
        )
        FORMAT JSONEachRow
    """

    query_params = {"team_id": inputs.team_id, "sample_size": sample_size}

    async with get_client(team_id=inputs.team_id) as client:
        response = await client.read_query(query, query_parameters=query_params)
        for line in response.decode("utf-8").splitlines():
            if line.strip():
                try:
                    row = json.loads(line)
                    sampled_ids = row["sampled_ids"]

                    # Sort sampled UUIDs to find percentile boundaries
                    sorted_ids = sorted(sampled_ids)

                    # Calculate boundaries at percentiles to divide into N partitions
                    # For parallelism=10, we need 9 boundaries at 10%, 20%, ..., 90%
                    boundaries = []
                    for i in range(1, parallelism):
                        percentile = i / parallelism
                        idx = int(percentile * len(sorted_ids))
                        idx = min(idx, len(sorted_ids) - 1)  # Clamp to valid index
                        boundaries.append(str(sorted_ids[idx]))

                    LOGGER.info(
                        f"Sampled {sample_size} person IDs from {total_count} total, "
                        f"generated {len(boundaries)} UUID boundaries for {parallelism} workers"
                    )

                    return UUIDBoundariesResult(boundaries=boundaries, total_persons=total_count)

                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    LOGGER.exception("Failed to parse UUID sampling result", line=line, error=str(e))
                    raise

    return UUIDBoundariesResult(boundaries=[], total_persons=0)


@temporalio.workflow.defn(name="backfill-precalculated-person-properties-coordinator")
class BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow(PostHogWorkflow):
    """Coordinator workflow that spawns multiple child workflows for parallel person processing."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BackfillPrecalculatedPersonPropertiesCoordinatorInputs:
        """Parse inputs from the management command CLI."""
        raise NotImplementedError("Use start_workflow() to trigger this workflow programmatically")

    @temporalio.workflow.run
    async def run(self, inputs: BackfillPrecalculatedPersonPropertiesCoordinatorInputs) -> None:
        """Run the coordinator workflow that spawns child workflows."""
        workflow_logger = temporalio.workflow.logger
        workflow_logger.info(
            f"Starting person properties precalculation coordinator for team {inputs.team_id} "
            f"with parallelism={inputs.parallelism}, {len(inputs.filters)} unique condition hashes"
        )

        # Step 1: Sample UUID boundaries to partition persons across workers
        boundaries_result = await temporalio.workflow.execute_activity(
            sample_uuid_boundaries_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )

        total_persons = boundaries_result.total_persons
        boundaries = boundaries_result.boundaries

        if total_persons == 0:
            workflow_logger.warning(f"No persons found for team {inputs.team_id}")
            return

        workflow_logger.info(
            f"Scheduling ~{total_persons} persons across {inputs.parallelism} child workflows "
            f"using {len(boundaries)} UUID boundaries, "
            f"in batches of {inputs.workflows_per_batch} every {inputs.batch_delay_minutes} minutes"
        )

        # Step 2: Create UUID range-based workflow configs
        # boundaries = [uuid1, uuid2, ..., uuid_N-1] for N workers
        # Worker 0: [None, uuid1)
        # Worker 1: [uuid1, uuid2)
        # ...
        # Worker N-1: [uuid_N-1, None)
        workflow_configs: list[ChildWorkflowConfig] = []
        for i in range(inputs.parallelism):
            min_uuid = boundaries[i - 1] if i > 0 else None
            max_uuid = boundaries[i] if i < len(boundaries) else None

            workflow_configs.append(
                ChildWorkflowConfig(
                    id=f"{temporalio.workflow.info().workflow_id}-child-{i}",
                    inputs=BackfillPrecalculatedPersonPropertiesInputs(
                        team_id=inputs.team_id,
                        filters=inputs.filters,
                        batch_size=inputs.batch_size,
                        min_person_id=min_uuid,
                        max_person_id=max_uuid,
                    ),
                    index=i + 1,
                )
            )

        total_workflows = len(workflow_configs)
        workflow_logger.info(f"Prepared {total_workflows} workflow configurations")

        # Step 4: Launch workflows in jittered batches
        workflows_scheduled = 0
        workflow_logger.info(
            f"About to start launching {total_workflows} workflows in batches of {inputs.workflows_per_batch}"
        )

        for batch_start in range(0, total_workflows, inputs.workflows_per_batch):
            batch_end = min(batch_start + inputs.workflows_per_batch, total_workflows)
            batch_configs = workflow_configs[batch_start:batch_end]
            batch_number = (batch_start // inputs.workflows_per_batch) + 1
            total_batches = math.ceil(total_workflows / inputs.workflows_per_batch)

            workflow_logger.info(
                f"Starting batch {batch_number}/{total_batches}: scheduling {len(batch_configs)} workflows"
            )

            # Start all workflows in current batch concurrently
            start_tasks = []
            for config in batch_configs:
                task = temporalio.workflow.start_child_workflow(
                    BackfillPrecalculatedPersonPropertiesWorkflow.run,
                    config["inputs"],
                    id=config["id"],
                    task_queue=settings.MESSAGING_TASK_QUEUE,
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                )
                start_tasks.append((task, config))

            # Await all starts in this batch concurrently
            # Note: start_child_workflow returns a coroutine that resolves when the child is started
            workflow_logger.info(f"Awaiting {len(start_tasks)} child workflow starts concurrently")

            for task, config in start_tasks:
                try:
                    # Await the child workflow start (not completion, due to ABANDON policy)
                    await task
                    workflows_scheduled += 1
                    min_uuid = config["inputs"].min_person_id or "MIN"
                    max_uuid = config["inputs"].max_person_id or "MAX"
                    workflow_logger.info(
                        f"Scheduled workflow {config['index']} for UUID range [{min_uuid}, {max_uuid})"
                    )
                except Exception as e:
                    workflow_logger.error(
                        f"Failed to start workflow {config['index']}: {e}",
                        exc_info=True,
                    )

            workflow_logger.info(
                f"Batch {batch_number}/{total_batches} completed: {len(batch_configs)} workflows started "
                f"({workflows_scheduled}/{total_workflows} total)"
            )

            # Wait before starting next batch (unless this is the last batch)
            if batch_end < total_workflows:
                delay_seconds = inputs.batch_delay_minutes * 60
                workflow_logger.info(f"Waiting {inputs.batch_delay_minutes} minutes before starting next batch...")
                await temporalio.workflow.sleep(delay_seconds)

        workflow_logger.info(
            f"Coordinator completed: scheduled {workflows_scheduled} child workflows in jittered batches"
        )

        # Explicitly log completion before returning
        workflow_logger.info(
            f"Coordinator workflow completed successfully for team {inputs.team_id}. "
            f"Total workflows scheduled: {workflows_scheduled}, "
            f"processing {len(inputs.filters)} unique condition hashes"
        )

        return None
