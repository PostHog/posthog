import time
import asyncio
import datetime as dt
import dataclasses
from typing import Any, Optional

import temporalio.activity
import temporalio.workflow
from structlog.contextvars import bind_contextvars

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_COHORT_MEMBERSHIP_CHANGED
from posthog.models.action import Action
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class RealtimeCohortCalculationWorkflowInputs:
    """Inputs for the realtime cohort calculation workflow."""

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


@temporalio.activity.defn
async def process_realtime_cohort_calculation_activity(inputs: RealtimeCohortCalculationWorkflowInputs) -> None:
    """Process a batch of actions with bytecode."""
    bind_contextvars()
    logger = LOGGER.bind()

    logger.info(f"Starting realtime cohort calculation workflow for range offset={inputs.offset}, limit={inputs.limit}")

    async with Heartbeater(details=(f"Starting to process actions (offset={inputs.offset})",)) as heartbeater:
        start_time = time.time()

        # Basic validation
        if not isinstance(inputs.days, int) or inputs.days < 0 or inputs.days > 365:
            raise ValueError(f"Invalid days value: {inputs.days}")
        if not isinstance(inputs.min_matches, int) or inputs.min_matches < 0:
            raise ValueError(f"Invalid min_matches value: {inputs.min_matches}")

        @database_sync_to_async
        def get_actions():
            # Only get actions that are not deleted and have bytecode
            # Only fetch the fields we need for efficiency
            queryset = Action.objects.filter(deleted=False, bytecode__isnull=False).only("id", "team_id")

            # Apply pagination
            queryset = (
                queryset.order_by("id")[inputs.offset : inputs.offset + inputs.limit]
                if inputs.limit
                else queryset[inputs.offset :]
            )

            return list(queryset)

        actions: list[Action] = await get_actions()

        actions_count = 0

        # Initialize Kafka producer once before the loop
        kafka_producer = KafkaProducer()

        # Process each action
        for idx, action in enumerate(actions, 1):
            # Update heartbeat progress every 100 actions to minimize overhead
            if idx % 100 == 0 or idx == len(actions):
                heartbeater.details = (f"Processing action {idx}/{len(actions)}",)

            # Log progress periodically
            if idx % 100 == 0 or idx == len(actions):
                logger.info(f"Processed {idx}/{len(actions)} actions so far")

            # Query ClickHouse for persons who performed event X at least N times over the last X days
            query = """
               SELECT
                    COALESCE(bcm.team_id, cmc.team_id) as team_id,
                    %(action_id)s as cohort_id,
                    COALESCE(bcm.person_id, cmc.person_id) as person_id,
                    now64() as last_updated,
                    CASE
                        WHEN
                            cmc.person_id IS NULL -- Does not exist in cohort_membership_changed
                            THEN 'entered' -- so, new member (or re-entered, as we filter members who left)
                        WHEN
                            bcm.person_id IS NULL -- There is no match in behavioral_cohorts_matches
                            THEN 'left' -- so, it left the cohort
                        ELSE
                            'unchanged' -- for all other cases, the membership did not change
                    END as status
                FROM
                (
                    SELECT
                        team_id,
                        person_id
                    FROM
                    (
                        SELECT team_id, distinct_id
                        FROM prefiltered_events
                        WHERE
                            team_id = %(team_id)s
                            AND condition = toString(%(action_id)s)
                            AND date >= now() - toIntervalDay(%(days)s)
                    ) AS pfe
                    INNER JOIN
                    (
                        SELECT
                            distinct_id,
                            argMax(person_id, version) as person_id
                        FROM person_distinct_id2
                        WHERE team_id = %(team_id)s
                        GROUP BY distinct_id
                        HAVING argMax(is_deleted, version) = 0
                    ) AS pdi2 ON pdi2.distinct_id = pfe.distinct_id
                    GROUP BY
                        team_id,
                        person_id
                    HAVING count() >= %(min_matches)s
                ) bcm
                FULL OUTER JOIN
                (
                    SELECT team_id, person_id, argMax(status, last_updated) as status
                    FROM cohort_membership
                    WHERE
                        team_id = %(team_id)s
                        AND cohort_id = %(action_id)s
                    GROUP BY team_id, person_id
                    HAVING status = 'entered'
                ) cmc ON bcm.team_id = cmc.team_id AND bcm.person_id = cmc.person_id
                WHERE status != 'unchanged'
                SETTINGS join_use_nulls = 1
                FORMAT JSONEachRow
            """

            try:
                with tags_context(
                    team_id=action.team_id,
                    feature=Feature.BEHAVIORAL_COHORTS,
                    product=Product.MESSAGING,
                    query_type="action_event_counts_per_person_per_day",
                ):
                    async with get_client(team_id=action.team_id) as client:
                        async for row in client.stream_query_as_jsonl(
                            query,
                            query_parameters={
                                "team_id": action.team_id,
                                "action_id": action.id,
                                "days": inputs.days,
                                "min_matches": inputs.min_matches,
                            },
                        ):
                            payload = {
                                "team_id": row["team_id"],
                                "cohort_id": row["cohort_id"],
                                "person_id": str(row["person_id"]),
                                "last_updated": str(row["last_updated"]),
                                "status": row["status"],
                            }
                            await asyncio.to_thread(
                                kafka_producer.produce,
                                topic=KAFKA_COHORT_MEMBERSHIP_CHANGED,
                                key=payload["person_id"],
                                data=payload,
                            )

            except Exception as e:
                logger.exception(
                    f"Error querying events for action {action.id}",
                    action_id=action.id,
                    error=str(e),
                )
                continue

            actions_count += 1

        end_time = time.time()
        duration_seconds = end_time - start_time
        duration_minutes = duration_seconds / 60

        heartbeater.details = (f"Completed: processed {actions_count} actions in {duration_minutes:.1f} minutes",)

        logger.info(
            f"Completed processing: processed {actions_count} actions in {duration_minutes:.1f} minutes ({duration_seconds:.1f} seconds)",
            actions_processed=actions_count,
            duration_seconds=duration_seconds,
            duration_minutes=duration_minutes,
            offset=inputs.offset,
            limit=inputs.limit,
        )


@temporalio.workflow.defn(name="realtime-cohort-calculation")
class RealtimeCohortCalculationWorkflow(PostHogWorkflow):
    """Child workflow that processes realtime cohort calculations."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> RealtimeCohortCalculationWorkflowInputs:
        """Parse inputs from the management command CLI."""
        return RealtimeCohortCalculationWorkflowInputs()

    @temporalio.workflow.run
    async def run(self, inputs: RealtimeCohortCalculationWorkflowInputs) -> None:
        """Run the workflow to process realtime cohort calculations."""
        workflow_logger = temporalio.workflow.logger
        workflow_logger.info(
            f"Starting realtime cohort calculation child workflow for range starting at offset={inputs.offset}"
        )

        # Process the batch of actions
        await temporalio.workflow.execute_activity(
            process_realtime_cohort_calculation_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=30),
            heartbeat_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                maximum_attempts=3,
                initial_interval=dt.timedelta(seconds=5),
                maximum_interval=dt.timedelta(seconds=30),
            ),
        )

        workflow_logger.info("Child workflow completed")
