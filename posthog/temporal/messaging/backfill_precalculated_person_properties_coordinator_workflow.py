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
    CohortFilters,
)

LOGGER = get_logger(__name__)


class ChildWorkflowConfig(TypedDict):
    """Type definition for child workflow configuration."""

    id: str
    inputs: BackfillPrecalculatedPersonPropertiesInputs
    start_uuid: str
    end_uuid: str
    index: int


@dataclasses.dataclass
class BackfillPrecalculatedPersonPropertiesCoordinatorInputs:
    """Inputs for the coordinator workflow that spawns child workflows."""

    team_id: int
    cohort_filters: list[CohortFilters]  # All cohorts and their filters
    parallelism: int = 10  # Number of child workflows to spawn
    batch_size: int = 1000  # Persons per batch within each worker
    workflows_per_batch: int = 5  # Number of workflows to start per batch
    batch_delay_minutes: int = 5  # Delay between batches in minutes

    @property
    def properties_to_log(self) -> dict[str, Any]:
        total_filters = sum(len(cf.filters) for cf in self.cohort_filters)
        return {
            "team_id": self.team_id,
            "cohort_count": len(self.cohort_filters),
            "cohort_ids": [cf.cohort_id for cf in self.cohort_filters],
            "filter_count": total_filters,
            "parallelism": self.parallelism,
            "batch_size": self.batch_size,
            "workflows_per_batch": self.workflows_per_batch,
            "batch_delay_minutes": self.batch_delay_minutes,
        }


@dataclasses.dataclass
class PersonCountResult:
    """Result from counting total persons."""

    count: int


@dataclasses.dataclass
class PersonUUIDRange:
    """UUID range for partitioning persons."""

    min_uuid: str
    max_uuid: str


@temporalio.activity.defn
async def get_person_count_activity(
    inputs: BackfillPrecalculatedPersonPropertiesCoordinatorInputs,
) -> PersonCountResult:
    """Get the total count of non-deleted persons for the team."""

    query = """
        SELECT count() as count
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

    # Execute query using async ClickHouse client
    async with get_client(team_id=inputs.team_id) as client:
        response = await client.read_query(query, query_parameters=query_params)
        for line in response.decode("utf-8").splitlines():
            if line.strip():
                try:
                    row = json.loads(line)
                    return PersonCountResult(count=int(row["count"]))
                except (json.JSONDecodeError, KeyError, ValueError):
                    LOGGER.exception("Failed to parse person count result", line=line)
                    raise

    return PersonCountResult(count=0)


@temporalio.activity.defn
async def get_person_uuid_range_activity(
    inputs: BackfillPrecalculatedPersonPropertiesCoordinatorInputs,
) -> PersonUUIDRange:
    """Get the min and max person UUIDs for the team to enable range partitioning."""

    query = """
        SELECT
            min(id) as min_uuid,
            max(id) as max_uuid
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

    # Execute query using async ClickHouse client
    async with get_client(team_id=inputs.team_id) as client:
        response = await client.read_query(query, query_parameters=query_params)
        for line in response.decode("utf-8").splitlines():
            if line.strip():
                try:
                    row = json.loads(line)
                    return PersonUUIDRange(min_uuid=str(row["min_uuid"]), max_uuid=str(row["max_uuid"]))
                except (json.JSONDecodeError, KeyError, ValueError):
                    LOGGER.exception("Failed to parse person UUID range result", line=line)
                    raise

    # If no persons found, return empty range
    return PersonUUIDRange(min_uuid="", max_uuid="")


def generate_uuid_ranges(min_uuid: str, max_uuid: str, num_ranges: int) -> list[tuple[str, str]]:
    """
    Generate UUID ranges for partitioning.

    Since UUIDs are lexicographically sortable strings, we can divide the space
    by interpolating between min and max UUID values.

    Returns list of (start_uuid, end_uuid) tuples.
    """
    if not min_uuid or not max_uuid or num_ranges <= 0:
        return []

    if num_ranges == 1:
        return [(min_uuid, max_uuid)]

    # Convert UUIDs to integers for mathematical operations
    # UUIDs are 32 hex characters, so we can treat them as base-16 integers
    try:
        min_int = int(min_uuid.replace("-", ""), 16)
        max_int = int(max_uuid.replace("-", ""), 16)
    except ValueError:
        # Fallback to simple string-based partitioning if UUID parsing fails
        LOGGER.warning("Failed to parse UUIDs as hex, using simple partitioning")
        return [(min_uuid, max_uuid)]

    if min_int >= max_int:
        # Edge case: all UUIDs are the same or invalid range
        return [(min_uuid, max_uuid)]

    # Calculate range size
    range_size = (max_int - min_int) // num_ranges
    if range_size == 0:
        # Very small range, just use the full range for all workers
        return [(min_uuid, max_uuid) for _ in range(num_ranges)]

    ranges = []
    for i in range(num_ranges):
        start_int = min_int + i * range_size
        end_int = min_int + (i + 1) * range_size if i < num_ranges - 1 else max_int

        # Convert back to UUID format
        start_hex = f"{start_int:032x}"
        end_hex = f"{end_int:032x}"

        # Format as UUID (8-4-4-4-12)
        start_uuid = f"{start_hex[:8]}-{start_hex[8:12]}-{start_hex[12:16]}-{start_hex[16:20]}-{start_hex[20:32]}"
        end_uuid = f"{end_hex[:8]}-{end_hex[8:12]}-{end_hex[12:16]}-{end_hex[16:20]}-{end_hex[20:32]}"

        ranges.append((start_uuid, end_uuid))

    return ranges


@temporalio.workflow.defn(name="backfill-precalculated-person-properties-coordinator")
class BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow(PostHogWorkflow):
    """Coordinator workflow that spawns multiple child workflows for parallel person processing.

    Key behavioral change: Child workflow IDs are now based on the coordinator workflow ID
    rather than individual cohort IDs. This allows a single set of child workflows to process
    multiple cohorts together, improving efficiency and reducing Temporal overhead.

    Child workflow ID format: {coordinator_workflow_id}-child-{worker_index}
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BackfillPrecalculatedPersonPropertiesCoordinatorInputs:
        """Parse inputs from the management command CLI."""
        raise NotImplementedError("Use start_workflow() to trigger this workflow programmatically")

    @temporalio.workflow.run
    async def run(self, inputs: BackfillPrecalculatedPersonPropertiesCoordinatorInputs) -> None:
        """Run the coordinator workflow that spawns child workflows."""
        workflow_logger = temporalio.workflow.logger
        cohort_ids = [cf.cohort_id for cf in inputs.cohort_filters]
        total_filters = sum(len(cf.filters) for cf in inputs.cohort_filters)
        workflow_logger.info(
            f"Starting person properties precalculation coordinator for {len(cohort_ids)} cohorts "
            f"(team {inputs.team_id}, cohorts {cohort_ids}) with parallelism={inputs.parallelism}, "
            f"processing {total_filters} total filters"
        )

        # Step 1: Get total count of persons for this team
        count_result = await temporalio.workflow.execute_activity(
            get_person_count_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )

        total_persons = count_result.count
        if total_persons == 0:
            workflow_logger.warning(f"No persons found for team {inputs.team_id}")
            return

        # Step 2: Get UUID range for partitioning
        uuid_range_result = await temporalio.workflow.execute_activity(
            get_person_uuid_range_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )

        if not uuid_range_result.min_uuid or not uuid_range_result.max_uuid:
            workflow_logger.warning(f"No valid UUID range found for team {inputs.team_id}")
            return

        workflow_logger.info(
            f"Partitioning {total_persons} persons across {inputs.parallelism} child workflows "
            f"using UUID range {uuid_range_result.min_uuid} to {uuid_range_result.max_uuid}, "
            f"in batches of {inputs.workflows_per_batch} every {inputs.batch_delay_minutes} minutes"
        )

        # Step 3: Generate UUID ranges for each worker
        uuid_ranges = generate_uuid_ranges(uuid_range_result.min_uuid, uuid_range_result.max_uuid, inputs.parallelism)

        if not uuid_ranges:
            workflow_logger.warning("Failed to generate UUID ranges")
            return

        # Step 4: Prepare all workflow configs first
        workflow_configs: list[ChildWorkflowConfig] = []
        for i, (start_uuid, end_uuid) in enumerate(uuid_ranges):
            workflow_configs.append(
                ChildWorkflowConfig(
                    id=f"{temporalio.workflow.info().workflow_id}-child-{i}",
                    inputs=BackfillPrecalculatedPersonPropertiesInputs(
                        team_id=inputs.team_id,
                        cohort_filters=inputs.cohort_filters,  # Pass all cohort filters
                        batch_size=inputs.batch_size,
                        start_uuid=start_uuid,
                        end_uuid=end_uuid,
                    ),
                    start_uuid=start_uuid,
                    end_uuid=end_uuid,
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
                    workflow_logger.info(
                        f"Scheduled workflow {config['index']} for UUID range {config['start_uuid']} to {config['end_uuid']}"
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
            f"Coordinator workflow completed successfully for team {inputs.team_id} "
            f"with {len(cohort_ids)} cohorts {cohort_ids}. "
            f"Total workflows scheduled: {workflows_scheduled}"
        )

        return None
