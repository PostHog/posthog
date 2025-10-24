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
    """Inputs for the coordinator workflow that spawns individual action workflows."""

    days: int = 30  # Number of days to look back
    min_matches: int = 3  # Minimum number of matches required
    parallelism: int = 10  # Legacy parameter - no longer used but kept for compatibility
    batch_size: int = 1000  # Number of workflows to start per batch (to avoid spikes)
    batch_delay_seconds: int = 60  # Delay between batches in seconds
    max_actions: int = 0  # Maximum number of actions to process (0 = all actions)

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "days": self.days,
            "min_matches": self.min_matches,
            "parallelism": self.parallelism,
            "batch_size": self.batch_size,
            "batch_delay_seconds": self.batch_delay_seconds,
            "max_actions": self.max_actions,
        }


@dataclasses.dataclass
class ActionsListResult:
    """Result from getting list of action IDs."""

    action_ids: list[int]


@temporalio.activity.defn
async def get_action_ids_activity(inputs: ActionsCoordinatorWorkflowInputs) -> ActionsListResult:
    """Get the list of action IDs with bytecode."""

    # Only get actions that are not deleted and have bytecode
    queryset = Action.objects.filter(deleted=False, bytecode__isnull=False).values_list("id", flat=True)

    action_ids: list[int] = await database_sync_to_async(lambda: list(queryset))()
    return ActionsListResult(action_ids=action_ids)


@temporalio.workflow.defn(name="actions-coordinator")
class ActionsCoordinatorWorkflow(PostHogWorkflow):
    """Coordinator workflow that spawns multiple child workflows for true parallelism."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ActionsCoordinatorWorkflowInputs:
        """Parse inputs from the management command CLI."""
        return ActionsCoordinatorWorkflowInputs()

    @temporalio.workflow.run
    async def run(self, inputs: ActionsCoordinatorWorkflowInputs) -> None:
        """Run the coordinator workflow that spawns individual action workflows."""
        workflow_logger = temporalio.workflow.logger
        workflow_logger.info("Starting actions coordinator - one workflow per action")

        # Step 1: Get list of action IDs
        actions_result = await temporalio.workflow.execute_activity(
            get_action_ids_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )

        action_ids = actions_result.action_ids
        if not action_ids:
            workflow_logger.warning("No actions found")
            return

        # Apply max_actions limit if specified
        if inputs.max_actions > 0 and len(action_ids) > inputs.max_actions:
            action_ids = action_ids[: inputs.max_actions]
            workflow_logger.info(f"Limited to first {inputs.max_actions} actions")

        workflow_logger.info(
            f"Scheduling {len(action_ids)} individual action workflows in batches of {inputs.batch_size}"
        )

        # Step 2: Import the single action workflow
        from posthog.temporal.messaging.action_single_workflow import ProcessActionInputs, ProcessActionWorkflow

        # Step 3: Launch individual action workflows in batches to avoid spikes
        workflows_scheduled = 0
        for i in range(0, len(action_ids), inputs.batch_size):
            batch_end = min(i + inputs.batch_size, len(action_ids))
            batch_action_ids = action_ids[i:batch_end]

            workflow_logger.info(f"Starting batch {i//inputs.batch_size + 1}: {len(batch_action_ids)} workflows")

            # Schedule workflows in current batch
            for action_id in batch_action_ids:
                child_id = f"{temporalio.workflow.info().workflow_id}-action-{action_id}"
                child_inputs = ProcessActionInputs(
                    action_id=action_id,
                    days=inputs.days,
                    min_matches=inputs.min_matches,
                )

                # Start child workflow - fire and forget, don't wait for result
                # Set parent_close_policy to ABANDON so child workflows continue after parent completes
                await temporalio.workflow.start_child_workflow(
                    ProcessActionWorkflow.run,
                    child_inputs,
                    id=child_id,
                    task_queue=MESSAGING_TASK_QUEUE,
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                )
                workflows_scheduled += 1

            workflow_logger.info(
                f"Scheduled batch {i//inputs.batch_size + 1}: {workflows_scheduled} total workflows scheduled"
            )

            # Wait between batches (except for the last batch)
            if batch_end < len(action_ids):
                workflow_logger.info(f"Waiting {inputs.batch_delay_seconds} seconds before next batch")
                await temporalio.workflow.sleep(inputs.batch_delay_seconds)

        workflow_logger.info(f"Coordinator completed: scheduled {workflows_scheduled} individual action workflows")
        return
