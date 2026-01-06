import math
import asyncio
import datetime as dt
import dataclasses
from typing import Any, TypedDict

from django.conf import settings

import temporalio.common
import temporalio.activity
import temporalio.workflow

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.messaging.backfill_precalculated_person_properties_workflow import (
    BackfillPrecalculatedPersonPropertiesInputs,
    BackfillPrecalculatedPersonPropertiesWorkflow,
    PersonPropertyFilter,
)

LOGGER = get_logger(__name__)


class ChildWorkflowConfig(TypedDict):
    """Type definition for child workflow configuration."""

    id: str
    inputs: BackfillPrecalculatedPersonPropertiesInputs
    offset: int
    limit: int
    index: int


@dataclasses.dataclass
class BackfillPrecalculatedPersonPropertiesCoordinatorInputs:
    """Inputs for the coordinator workflow that spawns child workflows."""

    team_id: int
    cohort_id: int
    filters: list[PersonPropertyFilter]  # Person property filters from cohort
    parallelism: int = 10  # Number of child workflows to spawn
    batch_size: int = 1000  # Persons per batch within each worker
    workflows_per_batch: int = 5  # Number of workflows to start per batch
    batch_delay_minutes: int = 5  # Delay between batches in minutes

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "cohort_id": self.cohort_id,
            "filter_count": len(self.filters),
            "parallelism": self.parallelism,
            "batch_size": self.batch_size,
            "workflows_per_batch": self.workflows_per_batch,
            "batch_delay_minutes": self.batch_delay_minutes,
        }


@dataclasses.dataclass
class PersonCountResult:
    """Result from counting total persons."""

    count: int


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
    """

    query_params = {"team_id": inputs.team_id}

    # Execute query using sync_execute in a thread to avoid blocking the event loop
    results = await asyncio.to_thread(
        sync_execute,
        query,
        query_params,
        workload=Workload.OFFLINE,
        team_id=inputs.team_id,
        ch_user=ClickHouseUser.COHORTS,
    )

    if results:
        return PersonCountResult(count=int(results[0][0]))

    return PersonCountResult(count=0)


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
            f"Starting person properties precalculation coordinator for cohort {inputs.cohort_id} "
            f"(team {inputs.team_id}) with parallelism={inputs.parallelism}"
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

        workflow_logger.info(
            f"Scheduling {total_persons} persons across {inputs.parallelism} child workflows "
            f"in batches of {inputs.workflows_per_batch} every {inputs.batch_delay_minutes} minutes"
        )

        # Step 2: Calculate ranges for each child workflow
        persons_per_workflow = math.ceil(total_persons / inputs.parallelism)

        # Step 3: Prepare all workflow configs first
        workflow_configs: list[ChildWorkflowConfig] = []
        for i in range(inputs.parallelism):
            offset = i * persons_per_workflow
            limit = min(persons_per_workflow, total_persons - offset)

            if limit <= 0:
                break

            workflow_configs.append(
                ChildWorkflowConfig(
                    id=f"{temporalio.workflow.info().workflow_id}-child-{i}",
                    inputs=BackfillPrecalculatedPersonPropertiesInputs(
                        team_id=inputs.team_id,
                        cohort_id=inputs.cohort_id,
                        filters=inputs.filters,
                        batch_size=inputs.batch_size,
                        offset=offset,
                        limit=limit,
                    ),
                    offset=offset,
                    limit=limit,
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
                        f"Scheduled workflow {config['index']} for persons {config['offset']}-{config['offset'] + config['limit'] - 1}"
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
            f"Coordinator workflow completed successfully for cohort {inputs.cohort_id}. "
            f"Total workflows scheduled: {workflows_scheduled}"
        )

        return None
