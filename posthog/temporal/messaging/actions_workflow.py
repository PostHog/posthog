import datetime as dt
import dataclasses
from typing import Any, Optional

import temporalio.activity
import temporalio.workflow

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.action import Action
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class ActionsWorkflowInputs:
    """Inputs for the actions processing workflow."""

    limit: Optional[int] = None
    offset: int = 0

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "offset": self.offset,
        }


@dataclasses.dataclass
class ProcessActionsResult:
    """Result from processing actions."""

    actions_processed: int
    offset: int


@temporalio.activity.defn
async def process_actions_activity(inputs: ActionsWorkflowInputs) -> ProcessActionsResult:
    """Process a batch of actions with bytecode."""
    logger = LOGGER.bind()

    # Only get actions that are not deleted and have bytecode
    # Only fetch the fields we need for efficiency
    queryset = Action.objects.filter(deleted=False, bytecode__isnull=False).only("id", "team_id", "steps_json")

    # Apply pagination
    queryset = (
        queryset.order_by("id")[inputs.offset : inputs.offset + inputs.limit]
        if inputs.limit
        else queryset[inputs.offset :]
    )

    actions_count = 0

    # Process each action
    for action in queryset:
        # Extract event name from the first step in steps_json
        if not action.steps_json or len(action.steps_json) == 0:
            continue

        first_step = action.steps_json[0] if isinstance(action.steps_json, list) else None
        if not first_step or not isinstance(first_step, dict):
            continue

        event_name = first_step.get("event")
        if not event_name:
            continue

        # Query ClickHouse for events matching this event name in the last 30 days
        # Group by person_id and date, count occurrences
        query = """
            SELECT
                person_id,
                toDate(timestamp) as event_date,
                count() as event_count
            FROM events
            WHERE
                team_id = %(team_id)s
                AND event = %(event_name)s
                AND timestamp >= now() - toIntervalDay(30)
                AND timestamp <= now()
            GROUP BY
                person_id,
                event_date
            ORDER BY
                event_date DESC,
                person_id
        """

        try:
            with tags_context(
                team_id=action.team_id,
                feature=Feature.ACTIONS,
                product=Product.MESSAGING,
                query_type="action_event_counts_per_person_per_day",
            ):
                sync_execute(
                    query,
                    {
                        "team_id": action.team_id,
                        "event_name": event_name,
                    },
                    ch_user=ClickHouseUser.DEFAULT,
                    workload=Workload.OFFLINE,
                )

        except Exception as e:
            logger.exception(
                f"Error querying events for action {action.id}",
                action_id=action.id,
                event_name=event_name,
                error=str(e),
            )
            continue

        actions_count += 1

    return ProcessActionsResult(
        actions_processed=actions_count,
        offset=inputs.offset,
    )


@temporalio.workflow.defn(name="actions-processing")
class ActionsWorkflow(PostHogWorkflow):
    """Child workflow that processes a subset of actions."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ActionsWorkflowInputs:
        """Parse inputs from the management command CLI."""
        return ActionsWorkflowInputs()

    @temporalio.workflow.run
    async def run(self, inputs: ActionsWorkflowInputs) -> ProcessActionsResult:
        """Run the workflow to process actions."""
        workflow_logger = temporalio.workflow.logger
        workflow_logger.info(
            f"Starting actions processing workflow",
            offset=inputs.offset,
            limit=inputs.limit,
        )

        # Process the batch of actions
        result = await temporalio.workflow.execute_activity(
            process_actions_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=10),
            retry_policy=temporalio.common.RetryPolicy(
                maximum_attempts=3,
                initial_interval=dt.timedelta(seconds=1),
                maximum_interval=dt.timedelta(seconds=10),
                backoff_coefficient=2,
            ),
        )

        workflow_logger.info(
            f"Completed processing {result.actions_processed} actions",
            offset=result.offset,
        )

        return result
