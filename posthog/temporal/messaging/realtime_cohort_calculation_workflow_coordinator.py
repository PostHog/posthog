import math
import datetime as dt
import dataclasses
from typing import Any, Optional, TypedDict

from django.conf import settings

import temporalio.common
import temporalio.activity
import temporalio.workflow

from posthog.models.cohort.cohort import Cohort, CohortType
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.messaging.realtime_cohort_calculation_workflow import (
    RealtimeCohortCalculationWorkflow,
    RealtimeCohortCalculationWorkflowInputs,
)

LOGGER = get_logger(__name__)


class WorkflowConfig(TypedDict):
    """Type definition for workflow configuration."""

    id: str
    inputs: RealtimeCohortCalculationWorkflowInputs
    offset: int
    limit: int
    index: int


@dataclasses.dataclass
class RealtimeCohortCalculationCoordinatorWorkflowInputs:
    """Inputs for the coordinator workflow that spawns child workflows."""

    parallelism: int = 10  # Number of child workflows to spawn
    workflows_per_batch: int = 5  # Number of workflows to start per batch
    batch_delay_minutes: int = 5  # Delay between batches in minutes
    team_id: Optional[int] = None  # Filter by team_id (optional)
    cohort_id: Optional[int] = None  # Filter to a specific cohort_id (optional)

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "parallelism": self.parallelism,
            "workflows_per_batch": self.workflows_per_batch,
            "batch_delay_minutes": self.batch_delay_minutes,
            "team_id": self.team_id,
            "cohort_id": self.cohort_id,
        }


@dataclasses.dataclass
class RealtimeCohortCalculationCountResult:
    """Result from counting total cohorts."""

    count: int


@temporalio.activity.defn
async def get_realtime_cohort_calculation_count_activity(
    inputs: RealtimeCohortCalculationCoordinatorWorkflowInputs,
) -> RealtimeCohortCalculationCountResult:
    """Get the total count of realtime cohorts."""

    @database_sync_to_async
    def get_cohort_count():
        # Only get cohorts that are not deleted and have cohort_type='realtime'
        queryset = Cohort.objects.filter(deleted=False, cohort_type=CohortType.REALTIME)
        if inputs.team_id is not None:
            queryset = queryset.filter(team_id=inputs.team_id)
        if inputs.cohort_id is not None:
            queryset = queryset.filter(id=inputs.cohort_id)
        return queryset.count()

    count = await get_cohort_count()
    return RealtimeCohortCalculationCountResult(count=count)


@temporalio.workflow.defn(name="realtime-cohort-calculation-coordinator")
class RealtimeCohortCalculationCoordinatorWorkflow(PostHogWorkflow):
    """Coordinator workflow that spawns multiple child workflows for true parallelism."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> RealtimeCohortCalculationCoordinatorWorkflowInputs:
        """Parse inputs from the management command CLI."""
        return RealtimeCohortCalculationCoordinatorWorkflowInputs()

    @temporalio.workflow.run
    async def run(self, inputs: RealtimeCohortCalculationCoordinatorWorkflowInputs) -> None:
        """Run the coordinator workflow that spawns child workflows."""
        workflow_logger = temporalio.workflow.logger
        workflow_logger.info(f"Starting realtime cohort calculation coordinator with parallelism={inputs.parallelism}")

        # Step 1: Get total count of cohorts
        count_result = await temporalio.workflow.execute_activity(
            get_realtime_cohort_calculation_count_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )

        total_cohorts = count_result.count
        if total_cohorts == 0:
            workflow_logger.warning("No realtime cohorts found")
            return

        workflow_logger.info(
            f"Scheduling {total_cohorts} cohorts across {inputs.parallelism} child workflows "
            f"in batches of {inputs.workflows_per_batch} every {inputs.batch_delay_minutes} minutes"
        )

        # Step 2: Calculate ranges for each child workflow
        cohorts_per_workflow = math.ceil(total_cohorts / inputs.parallelism)

        # Step 3: Prepare all workflow configs first
        workflow_configs: list[WorkflowConfig] = []
        for i in range(inputs.parallelism):
            offset = i * cohorts_per_workflow
            limit = min(cohorts_per_workflow, total_cohorts - offset)

            if limit <= 0:
                break

            workflow_configs.append(
                WorkflowConfig(
                    id=f"{temporalio.workflow.info().workflow_id}-child-{i}",
                    inputs=RealtimeCohortCalculationWorkflowInputs(
                        limit=limit,
                        offset=offset,
                        team_id=inputs.team_id,
                        cohort_id=inputs.cohort_id,
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
        for batch_start in range(0, total_workflows, inputs.workflows_per_batch):
            batch_end = min(batch_start + inputs.workflows_per_batch, total_workflows)
            batch_configs = workflow_configs[batch_start:batch_end]
            batch_number = (batch_start // inputs.workflows_per_batch) + 1
            total_batches = math.ceil(total_workflows / inputs.workflows_per_batch)

            workflow_logger.info(
                f"Starting batch {batch_number}/{total_batches}: scheduling {len(batch_configs)} workflows"
            )

            # Start all workflows in current batch
            for config in batch_configs:
                await temporalio.workflow.start_child_workflow(
                    RealtimeCohortCalculationWorkflow.run,
                    config["inputs"],
                    id=config["id"],
                    task_queue=settings.MESSAGING_TASK_QUEUE,
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                )
                workflows_scheduled += 1

                workflow_logger.info(
                    f"Scheduled workflow {config['index']} for cohorts {config['offset']}-{config['offset'] + config['limit'] - 1}"
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
        return
