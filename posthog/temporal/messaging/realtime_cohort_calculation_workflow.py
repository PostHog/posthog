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

        max_retries = 3
        retry_delay_seconds = 5
        base_timeout_seconds = 60
        backoff_factor = 3

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
            if idx % 100 == 0 or idx == len(cohorts):
                heartbeater.details = (f"Processing cohort {idx}/{len(cohorts)}",)
                logger.info(f"Processed {idx}/{len(cohorts)} cohorts so far")
            for retry_attempt in range(1, max_retries + 1):
                try:
                    # Exponential backoff: 60s, 180s (3min), 540s (9min)
                    cohort_max_execution_time = base_timeout_seconds * (backoff_factor ** (retry_attempt - 1))
                    current_members_sql, query_params = await build_query(cohort)
                    query_params = {
                        **query_params,
                        "team_id": cohort.team_id,
                        "cohort_id": cohort.id,
                        "max_execution_time": cohort_max_execution_time,
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
                        WHERE status != 'unchanged'
                        SETTINGS join_use_nulls = 1, max_execution_time = %(max_execution_time)s
                        FORMAT JSONEachRow
                    """

                    with tags_context(
                        team_id=cohort.team_id,
                        feature=Feature.BEHAVIORAL_COHORTS,
                        product=Product.MESSAGING,
                        query_type="realtime_cohort_calculation",
                    ):
                        async with get_client(team_id=cohort.team_id) as client:
                            async for row in client.stream_query_as_jsonl(final_query, query_parameters=query_params):
                                status = row["status"]
                                payload = {
                                    "team_id": cohort.team_id,
                                    "cohort_id": cohort.id,
                                    "person_id": str(row["person_id"]),
                                    "last_updated": dt.datetime.now(dt.UTC).isoformat(),
                                    "status": status,
                                }
                                await asyncio.to_thread(
                                    kafka_producer.produce,
                                    topic=KAFKA_COHORT_MEMBERSHIP_CHANGED,
                                    key=payload["person_id"],
                                    data=payload,
                                )

                                get_membership_changed_metric(status).add(1)

                    get_cohort_calculation_success_metric().add(1)
                    cohorts_count += 1
                    break
                except Exception as e:
                    is_last_attempt = retry_attempt == max_retries

                    if is_last_attempt:
                        get_cohort_calculation_failure_metric().add(1)

                        logger.exception(
                            f"Error calculating cohort {cohort.id} after {max_retries} attempts: {type(e).__name__}: {str(e)}",
                            cohort_id=cohort.id,
                            error_type=type(e).__name__,
                            error_message=str(e),
                            attempts=max_retries,
                        )
                    else:
                        next_timeout = base_timeout_seconds * (backoff_factor**retry_attempt)
                        logger.warning(
                            f"Error calculating cohort {cohort.id} (attempt {retry_attempt}/{max_retries}): {type(e).__name__}: {str(e)}. Retrying in {retry_delay_seconds}s with {next_timeout}s timeout...",
                            cohort_id=cohort.id,
                            error_type=type(e).__name__,
                            error_message=str(e),
                            attempt=retry_attempt,
                            next_timeout=next_timeout,
                        )
                        await asyncio.sleep(retry_delay_seconds)

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
