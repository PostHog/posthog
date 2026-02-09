import time
import random
import asyncio
import datetime as dt
import dataclasses
from typing import TYPE_CHECKING, Any, Optional

import temporalio.activity
import temporalio.workflow
from structlog.contextvars import bind_contextvars

from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import prepare_and_print_ast

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.hogql_cohort_query import HogQLRealtimeCohortQuery
from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_COHORT_MEMBERSHIP_CHANGED
from posthog.models.cohort.cohort import Cohort, CohortType
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

if TYPE_CHECKING:
    from posthog.kafka_client.client import _KafkaProducer

LOGGER = get_logger(__name__)


def get_cohort_calculation_success_metric():
    """Counter for successful cohort calculations."""
    return temporalio.activity.metric_meter().create_counter(
        "realtime_cohort_calculation_success", "Number of successful realtime cohort calculations"
    )


def get_cohort_calculation_failure_metric():
    """Counter for failed cohort calculations."""
    return temporalio.activity.metric_meter().create_counter(
        "realtime_cohort_calculation_failure", "Number of failed realtime cohort calculations"
    )


def get_membership_changed_metric(status: str):
    """Counter for cohort membership changes by status (entered/left)."""
    return (
        temporalio.activity.metric_meter()
        .with_additional_attributes({"status": status})
        .create_counter(
            "realtime_cohort_membership_changed",
            "Number of cohort membership changes (people entering or leaving cohorts)",
        )
    )


@dataclasses.dataclass
class RealtimeCohortCalculationWorkflowInputs:
    """Inputs for the realtime cohort calculation workflow."""

    limit: Optional[int] = None
    offset: int = 0
    cohort_id: Optional[int] = None
    # Dictionary mapping team_id to percentage (0.0 to 1.0)
    # Special key 0 means "default behavior" (PostHog team only when no specific teams)
    # Simple structure: specific team IDs that process all cohorts, and global percentage for others
    team_ids: set[int] = dataclasses.field(default_factory=set)  # Teams that process all cohorts
    global_percentage: float = 0.0  # Percentage for all other teams

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "offset": self.offset,
            "cohort_id": self.cohort_id,
            "team_ids": list(self.team_ids),
            "global_percentage": self.global_percentage,
        }


async def flush_kafka_batch(
    kafka_producer: "_KafkaProducer",
    pending_messages: list,
    cohort_id: int,
    idx: int,
    total_cohorts: int,
    heartbeater,
    logger,
    is_final: bool = False,
) -> int:
    """Flush a batch of Kafka messages and check for failures.

    Returns the number of messages flushed.
    """
    if not pending_messages:
        return 0

    batch_size = len(pending_messages)
    batch_type = "final " if is_final else ""
    heartbeater.details = (
        f"Flushing {batch_type}{batch_size} messages for cohort {idx}/{total_cohorts} (cohort_id={cohort_id})",
    )
    logger.info(
        f"Flushing {batch_type}batch of {batch_size} messages for cohort {cohort_id}",
        cohort_id=cohort_id,
        batch_size=batch_size,
    )

    await asyncio.to_thread(kafka_producer.flush)

    # Check for failures in this batch
    failed_count = 0
    for send_result in pending_messages:
        try:
            send_result.get(timeout=0)  # Non-blocking check
        except Exception as e:
            logger.warning(
                f"Kafka send result failure for cohort {cohort_id}: {e}",
                cohort_id=cohort_id,
                error=str(e),
                exception_type=type(e).__name__,
            )
            failed_count += 1

    if failed_count > 0:
        logger.error(
            f"Failed to send {failed_count}/{batch_size} Kafka messages for cohort {cohort_id}",
            cohort_id=cohort_id,
            failed_count=failed_count,
            batch_size=batch_size,
        )
        raise Exception(f"Failed to send {failed_count}/{batch_size} Kafka messages")

    return batch_size


@temporalio.activity.defn
async def process_realtime_cohort_calculation_activity(inputs: RealtimeCohortCalculationWorkflowInputs) -> None:
    """Process a batch of realtime cohorts using HogQLRealtimeCohortQuery."""
    bind_contextvars()
    logger = LOGGER.bind()

    logger.info(f"Starting realtime cohort calculation workflow for range offset={inputs.offset}, limit={inputs.limit}")

    async with Heartbeater(details=(f"Starting to process cohorts (offset={inputs.offset})",)) as heartbeater:
        start_time = time.time()

        @database_sync_to_async
        def get_cohorts():
            # If cohort_id is specified, just get that specific cohort
            if inputs.cohort_id is not None:
                queryset = Cohort.objects.filter(
                    deleted=False, cohort_type=CohortType.REALTIME, id=inputs.cohort_id
                ).select_related("team")
                return list(queryset)

            selected_cohorts = []

            # First, get all cohorts for teams that should process everything
            for team_id in inputs.team_ids:
                team_cohorts = list(
                    Cohort.objects.filter(deleted=False, cohort_type=CohortType.REALTIME, team_id=team_id)
                    .select_related("team")
                    .order_by("id")
                )
                selected_cohorts.extend(team_cohorts)

            # Handle global percentage for all other teams
            if inputs.global_percentage > 0.0:
                # Get cohorts from teams not in the force list
                if inputs.team_ids:
                    other_teams_cohorts = list(
                        Cohort.objects.filter(deleted=False, cohort_type=CohortType.REALTIME)
                        .exclude(team_id__in=inputs.team_ids)
                        .select_related("team")
                        .order_by("id")
                    )
                else:
                    other_teams_cohorts = list(
                        Cohort.objects.filter(deleted=False, cohort_type=CohortType.REALTIME)
                        .select_related("team")
                        .order_by("id")
                    )

                if other_teams_cohorts:
                    # Apply global percentage to other teams' cohorts (minimum 1)
                    num_to_include = max(1, int(len(other_teams_cohorts) * inputs.global_percentage))
                    # Randomly sample cohorts to ensure fairness
                    if num_to_include >= len(other_teams_cohorts):
                        # Include all cohorts if percentage would include everything
                        selected_other_cohorts = other_teams_cohorts
                    else:
                        # Randomly sample the specified number of cohorts
                        selected_other_cohorts = random.sample(other_teams_cohorts, num_to_include)
                    selected_cohorts.extend(selected_other_cohorts)

            # Remove duplicates and sort by ID for consistent ordering
            seen = set()
            unique_cohorts = []
            for cohort in selected_cohorts:
                if cohort.id not in seen:
                    seen.add(cohort.id)
                    unique_cohorts.append(cohort)

            unique_cohorts.sort(key=lambda c: c.id)

            # Apply pagination
            if inputs.limit:
                cohorts = unique_cohorts[inputs.offset : inputs.offset + inputs.limit]
            else:
                cohorts = unique_cohorts[inputs.offset :]

            return cohorts

        cohorts: list[Cohort] = await get_cohorts()

        cohorts_count = 0
        kafka_producer = KafkaProducer()

        @database_sync_to_async
        def build_query(cohort_obj):
            realtime_query = HogQLRealtimeCohortQuery(cohort=cohort_obj, team=cohort_obj.team)
            current_members_query = realtime_query.get_query()
            hogql_context = HogQLContext(
                team_id=cohort_obj.team_id,
                enable_select_queries=True,
                limit_context=LimitContext.COHORT_CALCULATION,
            )
            current_members_sql, _ = prepare_and_print_ast(current_members_query, hogql_context, "clickhouse")
            return current_members_sql, hogql_context.values

        for idx, cohort in enumerate(cohorts, 1):
            heartbeater.details = (f"Processing cohort {idx}/{len(cohorts)} (cohort_id={cohort.id})",)
            logger.info(f"Processing cohort {idx}/{len(cohorts)}", cohort_id=cohort.id)

            try:
                current_members_sql, query_params = await build_query(cohort)
                query_params = {
                    **query_params,
                    "team_id": cohort.team_id,
                    "cohort_id": cohort.id,
                }

                final_query = f"""
                    SELECT
                        COALESCE(current_matches.id, previous_members.person_id) as person_id,
                        CASE
                            WHEN previous_members.person_id IS NULL THEN 'entered'
                            WHEN current_matches.id IS NULL THEN 'left'
                            ELSE 'unchanged'
                        END as status
                    FROM
                    (
                        {current_members_sql}
                    ) AS current_matches
                    FULL OUTER JOIN
                    (
                        SELECT team_id, person_id, argMax(status, last_updated) as status
                        FROM cohort_membership
                        WHERE
                            team_id = %(team_id)s
                            AND cohort_id = %(cohort_id)s
                        GROUP BY team_id, person_id
                        HAVING status = 'entered'
                    ) previous_members ON current_matches.id = previous_members.person_id
                    WHERE status IN ('entered', 'left')
                    SETTINGS join_use_nulls = 1
                    FORMAT JSONEachRow
                """

                heartbeater.details = (f"Executing query for cohort {idx}/{len(cohorts)} (cohort_id={cohort.id})",)

                with tags_context(
                    team_id=cohort.team_id,
                    cohort_id=cohort.id,
                    feature=Feature.BEHAVIORAL_COHORTS,
                    product=Product.MESSAGING,
                    query_type="realtime_cohort_calculation",
                ):
                    status_counts = {"entered": 0, "left": 0}
                    pending_kafka_messages = []
                    FLUSH_BATCH_SIZE = 10_000  # Flush every 10k messages to allow heartbeats
                    # Count of messages successfully produced to Kafka (pending flush), excluding failed produce attempts
                    total_messages = 0
                    total_flushed = 0

                    logger.info(f"Executing query for cohort {cohort.id}", cohort_id=cohort.id)

                    async with get_client(team_id=cohort.team_id) as client:
                        async for row in client.stream_query_as_jsonl(
                            final_query,
                            query_parameters=query_params,
                        ):
                            person_id = row["person_id"]
                            status = row["status"]
                            status_counts[status] += 1
                            payload = {
                                "team_id": cohort.team_id,
                                "cohort_id": cohort.id,
                                "person_id": str(person_id),
                                # DateTime64(6) format required for Kafka JSONEachRow parsing into ClickHouse
                                "last_updated": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S.%f"),
                                "status": status,
                            }
                            # Produce to Kafka without blocking - collect send results for later flushing
                            try:
                                send_result = kafka_producer.produce(
                                    topic=KAFKA_COHORT_MEMBERSHIP_CHANGED,
                                    key=payload["person_id"],
                                    data=payload,
                                )
                                pending_kafka_messages.append(send_result)
                                total_messages += 1

                                # Flush in batches to allow heartbeats
                                if len(pending_kafka_messages) >= FLUSH_BATCH_SIZE:
                                    flushed = await flush_kafka_batch(
                                        kafka_producer,
                                        pending_kafka_messages,
                                        cohort.id,
                                        idx,
                                        len(cohorts),
                                        heartbeater,
                                        logger,
                                    )
                                    total_flushed += flushed
                                    pending_kafka_messages.clear()

                            except Exception as e:
                                logger.warning(
                                    f"Failed to produce Kafka message for person {payload['person_id']} in cohort {cohort.id}: {e}",
                                    cohort_id=cohort.id,
                                    person_id=payload["person_id"],
                                    error=str(e),
                                )
                                # Continue processing even if Kafka produce fails

                    # Flush any remaining messages
                    if pending_kafka_messages:
                        flushed = await flush_kafka_batch(
                            kafka_producer,
                            pending_kafka_messages,
                            cohort.id,
                            idx,
                            len(cohorts),
                            heartbeater,
                            logger,
                            is_final=True,
                        )
                        total_flushed += flushed

                    logger.info(
                        f"Successfully flushed {total_flushed} total messages for cohort {cohort.id}",
                        cohort_id=cohort.id,
                        total_messages=total_messages,
                        total_flushed=total_flushed,
                    )

                    if status_counts["entered"] > 0:
                        get_membership_changed_metric("entered").add(status_counts["entered"])
                    if status_counts["left"] > 0:
                        get_membership_changed_metric("left").add(status_counts["left"])

                get_cohort_calculation_success_metric().add(1)
                cohorts_count += 1
            except Exception as e:
                get_cohort_calculation_failure_metric().add(1)
                logger.exception(
                    f"Error calculating cohort {cohort.id}: {type(e).__name__}: {str(e)}",
                    cohort_id=cohort.id,
                    error_type=type(e).__name__,
                    error_message=str(e),
                )

        end_time = time.time()
        duration_seconds = end_time - start_time
        duration_minutes = duration_seconds / 60

        heartbeater.details = (f"Completed: processed {cohorts_count} cohorts in {duration_minutes:.1f} minutes",)

        logger.info(
            f"Completed processing: processed {cohorts_count} cohorts in {duration_minutes:.1f} minutes ({duration_seconds:.1f} seconds)",
            cohorts_processed=cohorts_count,
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
