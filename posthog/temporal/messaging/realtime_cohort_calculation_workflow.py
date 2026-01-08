import json
import time
import asyncio
import datetime as dt
import dataclasses
from typing import Any, Optional

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
    team_id: Optional[int] = None
    cohort_id: Optional[int] = None

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "offset": self.offset,
            "team_id": self.team_id,
            "cohort_id": self.cohort_id,
        }


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
            # Only get cohorts that are not deleted and have cohort_type='realtime'
            queryset = Cohort.objects.filter(deleted=False, cohort_type=CohortType.REALTIME).select_related("team")

            # Apply team_id filter if provided
            if inputs.team_id is not None:
                queryset = queryset.filter(team_id=inputs.team_id)

            # Apply cohort_id filter if provided - skip pagination when filtering by specific cohort
            if inputs.cohort_id is not None:
                queryset = queryset.filter(id=inputs.cohort_id)
            else:
                # Only apply pagination when not filtering by specific cohort
                queryset = (
                    queryset.order_by("id")[inputs.offset : inputs.offset + inputs.limit]
                    if inputs.limit
                    else queryset[inputs.offset :]
                )

            return list(queryset)

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
                    feature=Feature.BEHAVIORAL_COHORTS,
                    product=Product.MESSAGING,
                    query_type="realtime_cohort_calculation",
                ):
                    status_counts = {"entered": 0, "left": 0}
                    pending_kafka_messages = []
                    logger.info(f"Executing query for cohort {cohort.id}", cohort_id=cohort.id)

                    async with get_client(team_id=cohort.team_id) as client:
                        response = await client.read_query(
                            final_query,
                            query_parameters=query_params,
                        )
                        results = []
                        line_count = 0
                        for line in response.decode("utf-8").splitlines():
                            if line.strip():
                                try:
                                    row = json.loads(line)
                                    results.append((row["person_id"], row["status"]))
                                except (json.JSONDecodeError, KeyError) as e:
                                    logger.warning(
                                        f"Failed to parse cohort query result line: {e}",
                                        cohort_id=cohort.id,
                                        line=line,
                                        error=str(e),
                                    )
                                    # Skip malformed lines but continue processing
                                    continue
                                finally:
                                    line_count += 1
                                    # Yield control to event loop every 1000 lines to allow heartbeats to be sent
                                    if line_count % 1000 == 0:
                                        await asyncio.sleep(0)

                    # Process results
                    result_count = 0
                    for row in results:
                        person_id, status = row
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
                            # Run Kafka produce in thread pool to avoid blocking event loop
                            send_result = await asyncio.to_thread(
                                kafka_producer.produce,
                                topic=KAFKA_COHORT_MEMBERSHIP_CHANGED,
                                key=payload["person_id"],
                                data=payload,
                            )
                            pending_kafka_messages.append(send_result)
                        except Exception as e:
                            logger.warning(
                                f"Failed to produce Kafka message for person {payload['person_id']} in cohort {cohort.id}: {e}",
                                cohort_id=cohort.id,
                                person_id=payload["person_id"],
                                error=str(e),
                            )
                            # Continue processing even if Kafka produce fails

                        result_count += 1
                        # Yield control to event loop every 100 results to allow heartbeats to be sent
                        # We already await on to_thread above, but add explicit yield for good measure
                        if result_count % 100 == 0:
                            await asyncio.sleep(0)

                    # Flush all pending Kafka messages after processing
                    logger.info(
                        f"Query completed for cohort {cohort.id}. Total messages to flush: {len(pending_kafka_messages)}",
                        cohort_id=cohort.id,
                        message_count=len(pending_kafka_messages),
                    )

                    heartbeater.details = (
                        f"Flushing {len(pending_kafka_messages)} messages for cohort {idx}/{len(cohorts)} (cohort_id={cohort.id})",
                    )
                    await asyncio.to_thread(kafka_producer.flush)

                    # Check for any Kafka produce failures
                    failed_count = 0
                    for send_result in pending_kafka_messages:
                        try:
                            send_result.get(timeout=0)  # Non-blocking check
                        except Exception as e:
                            logger.warning(
                                f"Kafka send result failure for cohort {cohort.id}: {e}",
                                cohort_id=cohort.id,
                                error=str(e),
                                exception_type=type(e).__name__,
                            )
                            failed_count += 1

                    if failed_count > 0:
                        logger.error(
                            f"Failed to send {failed_count}/{len(pending_kafka_messages)} Kafka messages for cohort {cohort.id}",
                            cohort_id=cohort.id,
                            failed_count=failed_count,
                            total_count=len(pending_kafka_messages),
                        )
                        raise Exception(f"Failed to send {failed_count}/{len(pending_kafka_messages)} Kafka messages")

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
