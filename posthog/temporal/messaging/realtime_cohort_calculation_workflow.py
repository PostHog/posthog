import os
import time
import asyncio
import datetime as dt
import dataclasses
from typing import TYPE_CHECKING, Any, Optional

from django.utils import timezone

import temporalio.activity
import temporalio.workflow
from prometheus_client import Histogram
from structlog.contextvars import bind_contextvars

from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import prepare_and_print_ast

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.hogql_cohort_query import HogQLRealtimeCohortQuery
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_COHORT_MEMBERSHIP_CHANGED
from posthog.models.cohort.cohort import Cohort, CohortType
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger
from posthog.temporal.messaging.constants import get_percentile_bucket_label

if TYPE_CHECKING:
    from posthog.kafka_client.client import _KafkaProducer

# Configuration
FLUSH_BATCH_SIZE = int(os.environ.get("COHORT_KAFKA_FLUSH_BATCH_SIZE", "1000"))
DURATION_UPDATE_RELATIVE_THRESHOLD = 0.25  # Only update duration when change exceeds 25%

# Cohort calculation timing histograms
COHORT_CALCULATION_TOTAL_DURATION_HISTOGRAM = Histogram(
    "cohort_calculation_total_duration_seconds",
    "Total duration of cohort calculation from start to finish",
    ["percentile_bucket"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, float("inf")),
)

COHORT_QUERY_EXECUTION_DURATION_HISTOGRAM = Histogram(
    "cohort_query_execution_duration_seconds",
    "Duration of ClickHouse query execution for cohort calculation",
    ["percentile_bucket"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")),
)

COHORT_DURATION_UPDATE_HISTOGRAM = Histogram(
    "cohort_duration_update_seconds",
    "Duration of updating cohort duration in database",
    ["percentile_bucket"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, float("inf")),
)

# Kafka operation metrics
KAFKA_PRODUCE_DURATION_HISTOGRAM = Histogram(
    "cohort_kafka_produce_duration_seconds",
    "Time spent producing individual messages to Kafka",
    ["percentile_bucket"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")),
)

KAFKA_FLUSH_DURATION_HISTOGRAM = Histogram(
    "cohort_kafka_flush_duration_seconds",
    "Time spent flushing Kafka message batches",
    ["percentile_bucket"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, float("inf")),
)

# Query building metrics
QUERY_BUILD_DURATION_HISTOGRAM = Histogram(
    "cohort_query_build_duration_seconds",
    "Time spent building HogQL queries for cohort calculation",
    ["percentile_bucket"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")),
)

# Row processing metrics
ROW_PROCESSING_RATE_HISTOGRAM = Histogram(
    "cohort_rows_processed_per_second",
    "Rate of processing rows from ClickHouse query results",
    ["percentile_bucket"],
    buckets=(1, 10, 50, 100, 500, 1000, 5000, 10000, 50000, float("inf")),
)

# Child workflow total duration metrics
CHILD_WORKFLOW_TOTAL_DURATION_HISTOGRAM = Histogram(
    "realtime_cohort_child_total_duration_seconds",
    "Total duration of child workflow activity execution in seconds",
    ["percentile_bucket"],
    buckets=(1, 10, 30, 60, 120, 300, 600, 1800, 3600, float("inf")),
)

LOGGER = get_logger(__name__)

# Sampling rate for Kafka produce duration metrics to reduce overhead
KAFKA_PRODUCE_METRIC_SAMPLE_RATE = 1000


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


def get_membership_changed_metric(status: str, percentile_bucket: str):
    """Counter for cohort membership changes by status (entered/left) and percentile bucket."""
    return (
        temporalio.activity.metric_meter()
        .with_additional_attributes({"status": status, "percentile_bucket": percentile_bucket})
        .create_counter(
            "realtime_cohort_membership_changed",
            "Number of cohort membership changes (people entering or leaving cohorts)",
        )
    )


@dataclasses.dataclass
class RealtimeCohortCalculationWorkflowInputs:
    """Inputs for the realtime cohort calculation workflow."""

    # Array-based approach: coordinator provides specific cohort IDs to process
    cohort_ids: Optional[list[int]] = None

    # Keep cohort_id for backward compatibility with single cohort processing
    cohort_id: Optional[int] = None

    # Percentile bucket information for metrics
    duration_percentile_min: Optional[float] = None
    duration_percentile_max: Optional[float] = None

    @property
    def properties_to_log(self) -> dict[str, Any]:
        if self.cohort_id is not None:
            return {
                "cohort_id": self.cohort_id,
                "num_cohorts": 1,
            }
        elif self.cohort_ids is not None:
            return {
                "cohort_ids": self.cohort_ids[:10]
                if len(self.cohort_ids) > 10
                else self.cohort_ids,  # Log first 10 for brevity
                "num_cohorts": len(self.cohort_ids),
            }
        else:
            return {
                "num_cohorts": 0,
            }


async def flush_kafka_batch(
    kafka_producer: "_KafkaProducer",
    pending_messages: list,
    cohort_id: int,
    idx: int,
    total_cohorts: int,
    heartbeater,
    logger,
    percentile_bucket: str,
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

    # Time the Kafka flush operation
    flush_start_time = time.monotonic()
    await asyncio.to_thread(kafka_producer.flush)
    flush_duration = time.monotonic() - flush_start_time

    KAFKA_FLUSH_DURATION_HISTOGRAM.labels(percentile_bucket=percentile_bucket).observe(flush_duration)

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


@database_sync_to_async
def _batch_update_cohort_metrics(cohort_durations: dict[int, int]) -> int:
    """Batch update cohort durations and realtime calculation timestamp.

    Only updates duration_ms when it changed by more than DURATION_UPDATE_RELATIVE_THRESHOLD from the previous value.
    Always updates last_realtime_cohort_calculation_at for all processed cohorts.
    Does NOT update last_backfill_person_properties_at - that should only be updated by the backfilling person properties workflow.

    Returns count of cohorts that had their duration updated.
    """
    if not cohort_durations:
        return 0

    all_cohorts = list(Cohort.objects.filter(id__in=cohort_durations.keys()))
    now = timezone.now()
    duration_updates_count = 0

    for cohort in all_cohorts:
        cohort.last_realtime_cohort_calculation_at = now

        new_duration = cohort_durations[cohort.pk]
        previous_duration = cohort.last_calculation_duration_ms or 0

        # Only update duration_ms if it changed significantly
        if previous_duration > 0:
            percentage_change = abs(new_duration - previous_duration) / previous_duration
            should_update_duration = percentage_change > DURATION_UPDATE_RELATIVE_THRESHOLD
        else:
            # First calculation or previous was 0, always update duration
            should_update_duration = True

        if should_update_duration:
            cohort.last_calculation_duration_ms = new_duration
            duration_updates_count += 1

    # Single bulk_update for all cohorts — updates last_realtime_cohort_calculation_at and last_calculation_duration_ms
    if all_cohorts:
        Cohort.objects.bulk_update(
            all_cohorts,
            [
                "last_realtime_cohort_calculation_at",
                "last_calculation_duration_ms",
            ],
        )

    return duration_updates_count


@temporalio.activity.defn
async def process_realtime_cohort_calculation_activity(inputs: RealtimeCohortCalculationWorkflowInputs) -> None:
    """Process a batch of realtime cohorts using HogQLRealtimeCohortQuery."""
    bind_contextvars()
    logger = LOGGER.bind()

    if inputs.cohort_id is not None:
        num_cohorts_desc = "1 cohort"
    elif inputs.cohort_ids is not None:
        num_cohorts_desc = f"{len(inputs.cohort_ids)} cohorts"
    else:
        num_cohorts_desc = "0 cohorts"

    logger.info("Starting realtime cohort calculation workflow", num_cohorts_desc=num_cohorts_desc)

    async with Heartbeater(details=(f"Starting to process {num_cohorts_desc}",)) as heartbeater:
        start_time = time.monotonic()
        cohort_durations = {}
        percentile_bucket = get_percentile_bucket_label(inputs.duration_percentile_min, inputs.duration_percentile_max)

        @database_sync_to_async
        def get_cohorts():
            # Handle backward compatibility: single cohort_id
            if inputs.cohort_id is not None:
                queryset = Cohort.objects.filter(
                    deleted=False, cohort_type=CohortType.REALTIME, id=inputs.cohort_id
                ).select_related("team")
                return list(queryset)

            # Handle new approach: specific cohort IDs provided by coordinator
            if inputs.cohort_ids is not None:
                # Filter by the specific cohort IDs, maintaining order for consistent processing
                queryset = (
                    Cohort.objects.filter(
                        deleted=False,
                        cohort_type=CohortType.REALTIME,
                        id__in=inputs.cohort_ids,
                    )
                    .select_related("team")
                    .order_by("id")  # Critical: ordered by ID for consistent processing
                )
                return list(queryset)

            # No cohorts specified
            return []

        cohorts: list[Cohort] = await get_cohorts()

        cohorts_count = 0
        kafka_producer = get_producer(topic=KAFKA_COHORT_MEMBERSHIP_CHANGED)

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
            heartbeater.details = (f"Processing cohort {idx}/{len(cohorts)} (cohort_id={cohort.pk})",)
            logger.info("Processing cohort", cohort_index=idx, total_cohorts=len(cohorts), cohort_id=cohort.pk)

            # Start timing the entire cohort processing (query + Kafka production + flushing)
            cohort_start_time = time.monotonic()

            try:
                # Time the query building process
                query_build_start_time = time.monotonic()
                current_members_sql, query_params = await build_query(cohort)
                query_build_duration = time.monotonic() - query_build_start_time
                QUERY_BUILD_DURATION_HISTOGRAM.labels(percentile_bucket=percentile_bucket).observe(query_build_duration)

                query_params = {
                    **query_params,
                    "team_id": cohort.team_id,
                    "cohort_id": cohort.pk,
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

                heartbeater.details = (f"Executing query for cohort {idx}/{len(cohorts)} (cohort_id={cohort.pk})",)

                with tags_context(
                    team_id=cohort.team_id,
                    cohort_id=cohort.pk,
                    feature=Feature.BEHAVIORAL_COHORTS,
                    product=Product.MESSAGING,
                    query_type="realtime_cohort_calculation",
                ):
                    status_counts = {"entered": 0, "left": 0}
                    pending_kafka_messages = []
                    # Count of messages successfully produced to Kafka (pending flush), excluding failed produce attempts
                    total_messages = 0
                    total_flushed = 0

                    logger.info("Executing query for cohort", cohort_id=cohort.pk)

                    # Time the ClickHouse query execution
                    query_start_time = time.monotonic()
                    query_execution_complete = False

                    # Track row processing rate (will be set when first row arrives)
                    row_processing_start_time = None
                    rows_processed = 0

                    async with get_client(team_id=cohort.team_id) as client:
                        try:
                            async for row in client.stream_query_as_jsonl(
                                final_query,
                                query_parameters=query_params,
                            ):
                                # Record query execution time on first result (when streaming starts)
                                if not query_execution_complete:
                                    query_duration = time.monotonic() - query_start_time
                                    COHORT_QUERY_EXECUTION_DURATION_HISTOGRAM.labels(
                                        percentile_bucket=percentile_bucket
                                    ).observe(query_duration)
                                    query_execution_complete = True
                                    # Start row processing timer now that query is complete
                                    row_processing_start_time = time.monotonic()
                                person_id = row["person_id"]
                                status = row["status"]
                                status_counts[status] += 1
                                rows_processed += 1
                                payload = {
                                    "team_id": cohort.team_id,
                                    "cohort_id": cohort.pk,
                                    "person_id": str(person_id),
                                    # DateTime64(6) format required for Kafka JSONEachRow parsing into ClickHouse
                                    "last_updated": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S.%f"),
                                    "status": status,
                                }
                                # Produce to Kafka without blocking - collect send results for later flushing
                                try:
                                    produce_start_time = time.monotonic()
                                    send_result = kafka_producer.produce(
                                        topic=KAFKA_COHORT_MEMBERSHIP_CHANGED,
                                        key=payload["person_id"],
                                        data=payload,
                                    )
                                    produce_duration = time.monotonic() - produce_start_time
                                    # Sample every 1000th row to reduce histogram overhead for large cohorts
                                    if total_messages % KAFKA_PRODUCE_METRIC_SAMPLE_RATE == 0:
                                        KAFKA_PRODUCE_DURATION_HISTOGRAM.labels(
                                            percentile_bucket=percentile_bucket
                                        ).observe(produce_duration)

                                    pending_kafka_messages.append(send_result)
                                    total_messages += 1

                                    # Flush in batches to allow heartbeats
                                    if len(pending_kafka_messages) >= FLUSH_BATCH_SIZE:
                                        flushed = await flush_kafka_batch(
                                            kafka_producer,
                                            pending_kafka_messages,
                                            cohort.pk,
                                            idx,
                                            len(cohorts),
                                            heartbeater,
                                            logger,
                                            percentile_bucket,
                                        )
                                        total_flushed += flushed
                                        pending_kafka_messages.clear()

                                except Exception as e:
                                    logger.warning(
                                        f"Failed to produce Kafka message for person {payload['person_id']} in cohort {cohort.pk}: {e}",
                                        cohort_id=cohort.pk,
                                        person_id=payload["person_id"],
                                        error=str(e),
                                    )
                                    # Continue processing even if Kafka produce fails
                        finally:
                            # Ensure query execution time is recorded even for empty results or failures
                            if not query_execution_complete:
                                query_duration = time.monotonic() - query_start_time
                                COHORT_QUERY_EXECUTION_DURATION_HISTOGRAM.labels(
                                    percentile_bucket=percentile_bucket
                                ).observe(query_duration)

                    # Flush any remaining messages
                    if pending_kafka_messages:
                        flushed = await flush_kafka_batch(
                            kafka_producer,
                            pending_kafka_messages,
                            cohort.pk,
                            idx,
                            len(cohorts),
                            heartbeater,
                            logger,
                            percentile_bucket,
                            is_final=True,
                        )
                        total_flushed += flushed

                    # Calculate and record row processing rate
                    if rows_processed > 0 and row_processing_start_time is not None:
                        row_processing_duration = time.monotonic() - row_processing_start_time
                        if row_processing_duration > 0:
                            rows_per_second = rows_processed / row_processing_duration
                            ROW_PROCESSING_RATE_HISTOGRAM.labels(percentile_bucket=percentile_bucket).observe(
                                rows_per_second
                            )

                    logger.info(
                        f"Successfully flushed {total_flushed} total messages for cohort {cohort.pk}",
                        cohort_id=cohort.pk,
                        total_messages=total_messages,
                        total_flushed=total_flushed,
                        rows_processed=rows_processed,
                    )

                    if status_counts["entered"] > 0:
                        get_membership_changed_metric("entered", percentile_bucket).add(status_counts["entered"])
                    if status_counts["left"] > 0:
                        get_membership_changed_metric("left", percentile_bucket).add(status_counts["left"])

                # Calculate full cohort processing duration (not just query time)
                # Includes: query execution + Kafka message production + message flushing
                cohort_end_time = time.monotonic()
                duration_ms = int((cohort_end_time - cohort_start_time) * 1000)
                duration_seconds = duration_ms / 1000

                # Log slow cohorts for investigation
                if duration_seconds > 10:
                    logger.warning(
                        f"Slow cohort detected: cohort {cohort.pk} took {duration_seconds:.1f}s to process",
                        cohort_id=cohort.pk,
                        duration_seconds=duration_seconds,
                        duration_ms=duration_ms,
                        team_id=cohort.team_id,
                        cohort_name=cohort.name,
                        is_slow_cohort=True,
                    )

                # Record total cohort calculation duration
                COHORT_CALCULATION_TOTAL_DURATION_HISTOGRAM.labels(percentile_bucket=percentile_bucket).observe(
                    cohort_end_time - cohort_start_time
                )

                # Store duration for batch update at the end
                cohort_durations[cohort.pk] = duration_ms

                logger.info(
                    f"Cohort {cohort.pk} processing completed",
                    cohort_id=cohort.pk,
                    duration_ms=duration_ms,
                    duration_seconds=duration_seconds,
                )

                get_cohort_calculation_success_metric().add(1)
                cohorts_count += 1
            except Exception as e:
                get_cohort_calculation_failure_metric().add(1)
                logger.exception(
                    f"Error calculating cohort {cohort.pk}: {type(e).__name__}: {str(e)}",
                    cohort_id=cohort.pk,
                    error_type=type(e).__name__,
                    error_message=str(e),
                )

        # Batch update all cohort durations at once
        if cohort_durations:
            batch_update_start = time.monotonic()
            duration_updates_count = await _batch_update_cohort_metrics(cohort_durations)
            batch_update_duration = time.monotonic() - batch_update_start

            # Record batch update timing
            COHORT_DURATION_UPDATE_HISTOGRAM.labels(percentile_bucket=percentile_bucket).observe(batch_update_duration)

            logger.info(
                f"Batch duration update completed: {duration_updates_count}/{len(cohort_durations)} cohorts had duration updated",
                cohorts_processed=len(cohort_durations),
                duration_updates=duration_updates_count,
                batch_update_duration_ms=int(batch_update_duration * 1000),
            )

        end_time = time.monotonic()
        duration_seconds = end_time - start_time
        duration_minutes = duration_seconds / 60

        heartbeater.details = (f"Completed: processed {cohorts_count} cohorts in {duration_minutes:.1f} minutes",)

        # Record total child workflow duration
        CHILD_WORKFLOW_TOTAL_DURATION_HISTOGRAM.labels(percentile_bucket=percentile_bucket).observe(duration_seconds)

        logger.info(
            f"Completed processing: processed {cohorts_count} cohorts in {duration_minutes:.1f} minutes ({duration_seconds:.1f} seconds)",
            cohorts_processed=cohorts_count,
            duration_seconds=duration_seconds,
            duration_minutes=duration_minutes,
            range_info=num_cohorts_desc,
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
        if inputs.cohort_id is not None:
            workflow_logger.info(
                f"Starting realtime cohort calculation child workflow for cohort_id={inputs.cohort_id}"
            )
        elif inputs.cohort_ids is not None:
            workflow_logger.info(
                f"Starting realtime cohort calculation child workflow for {len(inputs.cohort_ids)} cohorts: {inputs.cohort_ids[:10]}{'...' if len(inputs.cohort_ids) > 10 else ''}"
            )
        else:
            workflow_logger.info("Starting realtime cohort calculation child workflow for empty batch")

        # Process the batch of actions
        await temporalio.workflow.execute_activity(
            process_realtime_cohort_calculation_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=60),
            heartbeat_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                maximum_attempts=3,
                initial_interval=dt.timedelta(seconds=5),
                maximum_interval=dt.timedelta(seconds=30),
            ),
        )

        workflow_logger.info("Child workflow completed")
