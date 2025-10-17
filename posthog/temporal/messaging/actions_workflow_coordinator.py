import math
import datetime as dt
import dataclasses
from typing import Any

import temporalio.common
import temporalio.activity
import temporalio.workflow

from posthog.constants import MESSAGING_TASK_QUEUE
from posthog.models.action import Action
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class ActionsCoordinatorWorkflowInputs:
    """Inputs for the coordinator workflow that spawns child workflows."""

    days: int = 30  # Number of days to look back
    min_matches: int = 3  # Minimum number of matches required
    parallelism: int = 10  # Number of child workflows to spawn

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "days": self.days,
            "min_matches": self.min_matches,
            "parallelism": self.parallelism,
        }


@dataclasses.dataclass
class ActionsCountResult:
    """Result from counting total actions."""

    count: int


@temporalio.activity.defn
async def get_actions_count_activity(inputs: ActionsCoordinatorWorkflowInputs) -> ActionsCountResult:
    """Get the total count of actions with bytecode."""

    # Only get actions that are not deleted and have bytecode
    queryset = Action.objects.filter(deleted=False, bytecode__isnull=False)

    count = await database_sync_to_async(queryset.count)()
    return ActionsCountResult(count=count)


@temporalio.workflow.defn(name="actions-coordinator")
class ActionsCoordinatorWorkflow(PostHogWorkflow):
    """Coordinator workflow that spawns multiple child workflows for true parallelism."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ActionsCoordinatorWorkflowInputs:
        """Parse inputs from the management command CLI."""
        return ActionsCoordinatorWorkflowInputs()

    @temporalio.workflow.run
    async def run(self, inputs: ActionsCoordinatorWorkflowInputs) -> None:
        """Run the coordinator workflow that spawns child workflows."""
        workflow_logger = temporalio.workflow.logger
        workflow_logger.info(f"Starting actions coordinator with parallelism={inputs.parallelism}")

        # Step 1: Get total count of actions
        count_result = await temporalio.workflow.execute_activity(
            get_actions_count_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )

        total_actions = count_result.count
        if total_actions == 0:
            workflow_logger.warning("No actions found")
            return

        workflow_logger.info(
            f"Scheduling {total_actions} actions with bytecode across {inputs.parallelism} child workflows"
        )

        # Step 2: Calculate ranges for each child workflow
        actions_per_workflow = math.ceil(total_actions / inputs.parallelism)

        # Step 3: Import the child workflow inputs and workflow class
        from posthog.temporal.messaging.actions_workflow import ActionsWorkflow, ActionsWorkflowInputs

        # Step 4: Launch child workflows - fire and forget
        workflows_scheduled = 0
        for i in range(inputs.parallelism):
            offset = i * actions_per_workflow
            limit = min(actions_per_workflow, total_actions - offset)

            if limit <= 0:
                break

            child_id = f"{temporalio.workflow.info().workflow_id}-child-{i}"
            child_inputs = ActionsWorkflowInputs(
                days=inputs.days,
                min_matches=inputs.min_matches,
                limit=limit,
                offset=offset,
            )

            # Start child workflow - fire and forget, don't wait for result
            # Set parent_close_policy to ABANDON so child workflows continue after parent completes
            await temporalio.workflow.start_child_workflow(
                ActionsWorkflow.run,
                child_inputs,
                id=child_id,
                task_queue=MESSAGING_TASK_QUEUE,
                parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
            )
            workflows_scheduled += 1

            workflow_logger.info(f"Scheduled child workflow {i+1} for actions {offset}-{offset+limit-1}")

        workflow_logger.info(f"Coordinator completed: scheduled {workflows_scheduled} child workflows")
        return
