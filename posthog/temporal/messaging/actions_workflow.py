import datetime as dt
import dataclasses
from typing import Any, Optional

import temporalio.activity
import temporalio.workflow
from structlog.contextvars import bind_contextvars

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.action import Action
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.logger import get_logger

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class ActionsWorkflowInputs:
    """Inputs for the actions processing workflow."""

    days: int = 30
    min_matches: int = 3
    limit: Optional[int] = None
    offset: int = 0

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "days": self.days,
            "min_matches": self.min_matches,
            "limit": self.limit,
            "offset": self.offset,
        }


@dataclasses.dataclass
class ProcessActionsResult:
    """Result from processing actions."""

    actions_processed: int
    offset: int


@temporalio.activity.defn
def process_actions_activity(inputs: ActionsWorkflowInputs) -> ProcessActionsResult:
    """Process a batch of actions with bytecode."""
    bind_contextvars()
    logger = LOGGER.bind()

    # Send heartbeat at start
    temporalio.activity.heartbeat()

    # Basic validation
    if not isinstance(inputs.days, int) or inputs.days < 0 or inputs.days > 365:
        raise ValueError(f"Invalid days value: {inputs.days}")
    if not isinstance(inputs.min_matches, int) or inputs.min_matches < 0:
        raise ValueError(f"Invalid min_matches value: {inputs.min_matches}")

    # Only get actions that are not deleted and have bytecode
    # Only fetch the fields we need for efficiency
    queryset = Action.objects.filter(deleted=False, bytecode__isnull=False).only("id", "team_id", "steps_json")

    # Apply pagination
    queryset = (
        queryset.order_by("id")[inputs.offset : inputs.offset + inputs.limit]
        if inputs.limit
        else queryset[inputs.offset :]
    )

    actions: list[Action] = list(queryset)

    actions_count = 0

    # Process each action with heartbeat to keep activity alive
    with HeartbeaterSync(logger=logger):
        for idx, action in enumerate(actions, 1):
            # Extract event name from the first step in steps_json
            if not action.steps_json or len(action.steps_json) == 0:
                continue

            first_step = action.steps_json[0] if isinstance(action.steps_json, list) else None
            if not first_step or not isinstance(first_step, dict):
                continue

            event_name = first_step.get("event")
            if not event_name:
                continue

            # Log progress periodically
            if idx % 100 == 0:
                logger.info(f"Processed {idx} actions so far")

            # Query ClickHouse for persons who performed event X at least N times over the last X days
            query = """
                SELECT
                    person_id,
                    count() as total_event_count
                FROM events
                WHERE
                    team_id = %(team_id)s
                    AND event = %(event_name)s
                    AND timestamp >= now() - toIntervalDay(%(days)s)
                    AND timestamp <= now()
                GROUP BY
                    person_id
                HAVING
                    count() >= %(min_matches)s
                ORDER BY
                    total_event_count DESC,
                    person_id
            """

            try:
                with tags_context(
                    team_id=action.team_id,
                    feature=Feature.BEHAVIORAL_COHORTS,
                    product=Product.MESSAGING,
                    query_type="action_event_counts_per_person_per_day",
                ):
                    sync_execute(
                        query,
                        {
                            "team_id": action.team_id,
                            "event_name": event_name,
                            "days": inputs.days,
                            "min_matches": inputs.min_matches,
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
            start_to_close_timeout=dt.timedelta(minutes=30),
            heartbeat_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                maximum_attempts=3,
                initial_interval=dt.timedelta(seconds=5),
                maximum_interval=dt.timedelta(seconds=30),
            ),
        )

        workflow_logger.info(
            f"Completed processing {result.actions_processed} actions",
            offset=result.offset,
        )

        return result
