import os
import json
import time
import asyncio
import datetime as dt
import dataclasses
from typing import TYPE_CHECKING, Any

import temporalio.common
import temporalio.activity
import temporalio.workflow
import temporalio.exceptions
from structlog.contextvars import bind_contextvars

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger
from posthog.temporal.messaging.filter_storage import get_filters_and_properties
from posthog.temporal.messaging.types import PersonPropertyFilter

from common.hogvm.python.execute import execute_bytecode

if TYPE_CHECKING:
    pass

LOGGER = get_logger(__name__)


def format_cohort_ids_for_logging(cohort_ids: list[int]) -> str:
    """Format cohort IDs for logging, showing simplified text for large sets.

    Args:
        cohort_ids: List of cohort IDs

    Returns:
        String representation of cohort IDs, or simplified text if too many
    """
    if len(cohort_ids) > 10:
        return f"More than 10... ({len(cohort_ids)} total)"
    else:
        return str(cohort_ids)


def parse_person_properties(properties_raw: Any, person_id: str) -> dict[str, Any]:
    """Parse person properties from ClickHouse, handling both string and dict formats.

    Args:
        properties_raw: The raw properties value from ClickHouse (can be string, dict, or None)
        person_id: The person ID for logging purposes

    Returns:
        A dictionary of person properties (empty dict if parsing fails or non-dict value)
    """
    if isinstance(properties_raw, str):
        try:
            parsed = json.loads(properties_raw)
            # Ensure we only return dicts (handles null, numbers, arrays, etc.)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            LOGGER.warning("Failed to parse properties for person", person_id=person_id)
            return {}
    else:
        return properties_raw if isinstance(properties_raw, dict) else {}


async def flush_kafka_batch_async(
    kafka_results: list,
    kafka_producer,
    team_id: int,
    logger,
    flush_duration_metric=None,
) -> int:
    """Flush Kafka messages asynchronously and return count of successful messages.

    Args:
        kafka_results: List of ProduceResult objects from Kafka send operations
        kafka_producer: Kafka producer instance
        team_id: Team ID for logging
        logger: Logger instance
        flush_duration_metric: Optional metric to record flush duration

    Returns:
        Number of successfully processed messages
    """
    if not kafka_results:
        return 0

    # Count the successful produce results
    successful_count = len(kafka_results)  # All results in the list are successful ones

    # Time the Kafka flush operation for performance monitoring
    flush_start_time = time.monotonic()
    await asyncio.to_thread(kafka_producer.flush)
    flush_duration = time.monotonic() - flush_start_time

    # Record flush performance metrics if metric is provided
    if flush_duration_metric:
        flush_duration_metric.record(flush_duration, {"team_id": str(team_id)})

    logger.info(
        f"Async flushed batch in {flush_duration:.3f}s: {successful_count} successful messages",
        team_id=team_id,
        successful_messages=successful_count,
        total_messages=len(kafka_results),
        flush_duration_seconds=flush_duration,
    )

    return successful_count


def get_person_properties_backfill_success_metric():
    """Counter for successful person properties backfills."""
    return temporalio.activity.metric_meter().create_counter(
        "person_properties_backfill_success", "Number of successful person properties backfills"
    )


def get_person_properties_backfill_failure_metric():
    """Counter for failed person properties backfills."""
    return temporalio.activity.metric_meter().create_counter(
        "person_properties_backfill_failure", "Number of failed person properties backfills"
    )


def get_query_duration_metric():
    """Histogram for ClickHouse query durations."""
    return temporalio.activity.metric_meter().create_histogram_float(
        "backfill_clickhouse_query_duration_seconds", "Duration of ClickHouse queries in seconds", unit="seconds"
    )


def get_person_processing_rate_metric():
    """Gauge for person processing rate."""
    return temporalio.activity.metric_meter().create_histogram_float(
        "backfill_person_processing_rate", "Persons processed per second", unit="persons/second"
    )


def get_filter_evaluation_duration_metric():
    """Histogram for filter evaluation durations."""
    return temporalio.activity.metric_meter().create_histogram_float(
        "backfill_filter_evaluation_duration_seconds", "Duration of filter evaluations in seconds", unit="seconds"
    )


def get_flush_duration_metric():
    """Histogram for Kafka flush durations."""
    return temporalio.activity.metric_meter().create_histogram_float(
        "backfill_kafka_flush_duration_seconds", "Duration of Kafka flush operations in seconds", unit="seconds"
    )


@dataclasses.dataclass
class CohortFilters:
    """Filters for a specific cohort."""

    cohort_id: int
    filters: list[PersonPropertyFilter]


@dataclasses.dataclass
class BackfillPrecalculatedPersonPropertiesResult:
    """Result from backfilling precalculated person properties."""

    persons_processed: int
    events_produced: int
    events_flushed: int
    last_person_id: str | None  # None if no persons were processed
    duration_seconds: float


@dataclasses.dataclass
class BackfillPrecalculatedPersonPropertiesInputs:
    """Inputs for the precalculated person properties backfill workflow."""

    team_id: int
    filter_storage_key: str  # Redis key containing the filters
    cohort_ids: list[int]  # All cohort IDs being processed
    batch_size: int = 1000
    start_person_id: str = "00000000-0000-0000-0000-000000000000"  # Starting person ID for this batch
    end_person_id: str = "ffffffff-ffff-ffff-ffff-ffffffffffff"  # Ending person ID for this batch

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "cohort_count": len(self.cohort_ids),
            "cohort_ids": format_cohort_ids_for_logging(self.cohort_ids),
            "filter_storage_key": self.filter_storage_key,
            "batch_size": self.batch_size,
            "start_person_id": self.start_person_id,
            "end_person_id": self.end_person_id,
        }


@temporalio.activity.defn
async def backfill_precalculated_person_properties_activity(
    inputs: BackfillPrecalculatedPersonPropertiesInputs,
) -> BackfillPrecalculatedPersonPropertiesResult:
    """
    Backfill precalculated person properties for a batch of persons across multiple cohorts.

    Queries the current state of persons from the persons table and evaluates them
    against all provided filters from multiple cohorts, writing results to the
    precalculated_person_properties table. Each person is evaluated against all filters
    from all cohorts in a single pass for efficiency.
    """
    bind_contextvars()
    cohort_ids = inputs.cohort_ids
    logger = LOGGER.bind(
        team_id=inputs.team_id, cohort_count=len(cohort_ids), cohort_ids=format_cohort_ids_for_logging(cohort_ids)
    )

    # Load filters and person properties from Redis storage without blocking the event loop
    storage_result = await asyncio.to_thread(get_filters_and_properties, inputs.filter_storage_key)
    if storage_result is None:
        raise temporalio.exceptions.ApplicationError(
            f"Filters not found in storage for key: {inputs.filter_storage_key}. "
            "The Redis payload may have expired; please re-store the filters and restart the workflow.",
            type="MissingFilters",
            non_retryable=True,
        )

    filters, person_properties = storage_result
    logger.info(f"Loaded {len(filters)} filters from storage key: {inputs.filter_storage_key}")

    # Early abort if no filters to process
    if not filters:
        logger.info("No filters found for real-time cohorts, aborting backfill")
        return BackfillPrecalculatedPersonPropertiesResult(
            persons_processed=0,
            events_produced=0,
            events_flushed=0,
            last_person_id=None,
            duration_seconds=0.0,
        )

    if person_properties:
        logger.info(f"Detected {len(person_properties)} unique person properties in use: {person_properties}")
    else:
        logger.info("No person properties detected or using legacy storage format")

    logger.info(
        f"Starting person properties precalculation for {len(cohort_ids)} cohorts {format_cohort_ids_for_logging(cohort_ids)}, "
        f"processing {len(filters)} total filters from person ID {inputs.start_person_id} to {inputs.end_person_id} "
        f"with batch size {inputs.batch_size} ({len(filters)} filters = ~{inputs.batch_size * len(filters)} events per batch)"
    )

    async with Heartbeater(
        details=(f"Processing persons from {inputs.start_person_id} to {inputs.end_person_id}",)
    ) as heartbeater:
        start_time = time.time()
        kafka_producer = KafkaProducer()

        total_processed = 0
        total_events_produced = 0
        total_flushed = 0
        # Use batched Kafka flushing to avoid memory buildup and reduce data loss risk
        kafka_results = []  # Store ProduceResult objects for periodic flushing
        KAFKA_FLUSH_BATCH_SIZE = int(
            os.environ.get("BACKFILL_KAFKA_FLUSH_BATCH_SIZE", "1000")
        )  # Configurable flush size

        # Create metrics once for activity
        query_duration_metric = None
        person_processing_rate_metric = None
        filter_evaluation_duration_metric = None
        try:
            metric_meter = temporalio.activity.metric_meter()
            query_duration_metric = metric_meter.create_histogram_float(
                "backfill_clickhouse_query_duration_seconds",
                "Duration of ClickHouse queries in seconds",
                unit="seconds",
            )
            person_processing_rate_metric = metric_meter.create_histogram_float(
                "backfill_person_processing_rate", "Persons processed per second", unit="persons/second"
            )
            filter_evaluation_duration_metric = metric_meter.create_histogram_float(
                "backfill_filter_evaluation_duration_seconds",
                "Duration of filter evaluations in seconds",
                unit="seconds",
            )
        except RuntimeError:
            # Not in activity context (e.g., during tests), skip metrics
            pass

        # Build optimized query to only fetch needed person properties
        MAX_OPTIMIZED_PROPERTIES = 100  # Safety limit to avoid query complexity issues
        property_alias_mapping = {}

        if person_properties and len(person_properties) <= MAX_OPTIMIZED_PROPERTIES:
            # Only select the specific properties we need
            property_selects = []

            for i, prop in enumerate(person_properties):
                # Use JSON extract to get only the specific property
                escaped_prop = prop.replace("'", "''")  # Escape single quotes for SQL safety
                safe_alias = f"prop_{i}"  # Use safe numeric aliases
                property_selects.append(f"JSONExtractString(properties, '{escaped_prop}') as `{safe_alias}`")
                property_alias_mapping[safe_alias] = prop

            properties_clause = ",\n                ".join(property_selects)
            logger.info(
                f"Optimized query: fetching only {len(person_properties)} specific properties instead of all properties"
            )
        else:
            # Fallback to all properties if we have too many properties or can't determine which ones are needed
            properties_clause = "properties"
            if person_properties and len(person_properties) > MAX_OPTIMIZED_PROPERTIES:
                logger.warning(
                    f"Too many properties ({len(person_properties)} > {MAX_OPTIMIZED_PROPERTIES}) - falling back to fetching all properties for performance"
                )
            else:
                logger.warning(
                    "Falling back to fetching all properties - could not determine specific properties needed"
                )

        persons_query = f"""
            SELECT
                id as person_id,
                {properties_clause}
            FROM person FINAL
            WHERE team_id = %(team_id)s
              AND id >= %(start_person_id)s
              AND id <= %(end_person_id)s
              AND is_deleted = 0
            ORDER BY id
            FORMAT JSONEachRow
        """

        query_params = {
            "team_id": inputs.team_id,
            "start_person_id": inputs.start_person_id,
            "end_person_id": inputs.end_person_id,
        }

        last_person_id = inputs.start_person_id
        batch_count = 0

        with tags_context(
            team_id=inputs.team_id,
            feature=Feature.BEHAVIORAL_COHORTS,
            product=Product.MESSAGING,
            query_type="person_properties_backfill",
        ):
            async with get_client(team_id=inputs.team_id) as client:
                # Time the ClickHouse query execution
                query_start_time = time.monotonic()

                async for row in client.stream_query_as_jsonl(persons_query, query_parameters=query_params):
                    batch_count += 1
                    person_id = str(row["person_id"])
                    last_person_id = person_id  # Track the last person ID for next cursor

                    # Handle both optimized (individual property columns) and fallback (full properties JSON) formats
                    if person_properties and "properties" not in row:
                        # Optimized format: reconstruct properties dict from individual columns using alias mapping
                        reconstructed_properties = {}
                        for alias, original_prop_name in property_alias_mapping.items():
                            value = row.get(alias)
                            if value:  # Only include non-empty values
                                reconstructed_properties[original_prop_name] = value

                        parsed_properties = parse_person_properties(reconstructed_properties, person_id)
                    else:
                        # Fallback format: use full properties JSON
                        parsed_properties = parse_person_properties(row.get("properties"), person_id)

                    # Evaluate each filter for this person
                    person_filter_start = time.monotonic()
                    for filter_obj in filters:
                        # Execute the filter bytecode to get the result
                        try:
                            # Execute bytecode with person properties
                            result = execute_bytecode(filter_obj.bytecode, parsed_properties)

                            # If filter matches, create an event for each cohort
                            if result:
                                for cohort_id in filter_obj.cohort_ids:
                                    event = {
                                        "team_id": inputs.team_id,
                                        "distinct_id": person_id,
                                        "person_id": person_id,
                                        "cohort_id": cohort_id,
                                        "condition_hash": filter_obj.condition_hash,
                                        "property_key": filter_obj.property_key,
                                        "result": result,
                                    }

                                    # Produce to Kafka and collect ProduceResult objects for flushing
                                    try:
                                        produce_result = kafka_producer.produce(
                                            topic=KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES,
                                            data=event,
                                        )
                                        kafka_results.append(produce_result)
                                        total_events_produced += 1

                                        # Periodically flush Kafka batches to avoid memory buildup
                                        if len(kafka_results) >= KAFKA_FLUSH_BATCH_SIZE:
                                            logger.info(
                                                f"Flushing {len(kafka_results)} Kafka messages (batch size: {KAFKA_FLUSH_BATCH_SIZE})"
                                            )
                                            batch_flushed = await flush_kafka_batch_async(
                                                kafka_results,
                                                kafka_producer,
                                                inputs.team_id,
                                                logger,
                                            )
                                            total_flushed += batch_flushed
                                            kafka_results.clear()  # Clear the batch after flushing

                                    except Exception as e:
                                        logger.warning(
                                            f"Failed to produce Kafka message for person {person_id}: {e}",
                                            person_id=person_id,
                                            error=str(e),
                                        )
                                        # Continue processing even if Kafka produce fails
                        except Exception as e:
                            logger.warning(
                                f"Failed to execute filter bytecode for person {person_id}: {e}",
                                person_id=person_id,
                                condition_hash=filter_obj.condition_hash,
                                error=str(e),
                            )

                    # Record filter evaluation timing for this person
                    person_filter_duration = time.monotonic() - person_filter_start
                    if filter_evaluation_duration_metric:
                        filter_evaluation_duration_metric.record(
                            person_filter_duration, {"team_id": str(inputs.team_id), "filter_count": str(len(filters))}
                        )

        # Record query timing and person processing rate
        query_duration = time.monotonic() - query_start_time
        if query_duration_metric and batch_count > 0:
            query_duration_metric.record(query_duration, {"team_id": str(inputs.team_id)})

        if person_processing_rate_metric and query_duration > 0:
            processing_rate = batch_count / query_duration
            person_processing_rate_metric.record(processing_rate, {"team_id": str(inputs.team_id)})

        logger.info(
            f"Processed {batch_count} persons from {inputs.start_person_id} to {last_person_id} (range: {inputs.start_person_id} - {inputs.end_person_id})"
        )
        total_processed = batch_count

        # Update heartbeat
        heartbeater.details = (
            f"Processed {total_processed} persons, produced {total_events_produced} events, pending {len(kafka_results)} messages",
        )

        # Flush all collected Kafka results
        if kafka_results:
            logger.info(f"Final flush of {len(kafka_results)} Kafka results", team_id=inputs.team_id)
            final_flushed = await flush_kafka_batch_async(
                kafka_results,
                kafka_producer,
                inputs.team_id,
                logger,
            )
            total_flushed += final_flushed

        end_time = time.time()
        duration_seconds = end_time - start_time

        get_person_properties_backfill_success_metric().add(1)

        logger.info(
            f"Completed person properties precalculation: processed {total_processed} persons, "
            f"produced {total_events_produced} events, flushed {total_flushed} in {duration_seconds:.1f} seconds",
            persons_processed=total_processed,
            events_produced=total_events_produced,
            events_flushed=total_flushed,
            duration_seconds=duration_seconds,
        )

        return BackfillPrecalculatedPersonPropertiesResult(
            persons_processed=total_processed,
            events_produced=total_events_produced,
            events_flushed=total_flushed,
            last_person_id=last_person_id if batch_count > 0 else None,
            duration_seconds=duration_seconds,
        )


@temporalio.workflow.defn(name="backfill-precalculated-person-properties")
class BackfillPrecalculatedPersonPropertiesWorkflow(PostHogWorkflow):
    """Workflow that backfills precalculated person properties for a team's cohorts."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BackfillPrecalculatedPersonPropertiesInputs:
        """Parse inputs from the management command CLI."""
        # This would be called programmatically, not from CLI
        raise NotImplementedError("Use start_workflow() to trigger this workflow programmatically")

    @temporalio.workflow.run
    async def run(
        self, inputs: BackfillPrecalculatedPersonPropertiesInputs
    ) -> BackfillPrecalculatedPersonPropertiesResult:
        """Run the workflow to backfill precalculated person properties for a specific ID range."""
        workflow_logger = temporalio.workflow.logger
        cohort_ids = inputs.cohort_ids
        workflow_logger.info(
            f"Starting person properties precalculation for {len(cohort_ids)} cohorts {format_cohort_ids_for_logging(cohort_ids)} "
            f"(team {inputs.team_id}, range: {inputs.start_person_id} - {inputs.end_person_id})"
        )

        # Process the specific ID range
        result = await temporalio.workflow.execute_activity(
            backfill_precalculated_person_properties_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(hours=12),  # Long timeout for large batches
            heartbeat_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                maximum_attempts=3,
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(minutes=1),
            ),
        )

        workflow_logger.info(
            f"Completed person properties precalculation: processed {result.persons_processed} persons, "
            f"produced {result.events_produced} events, flushed {result.events_flushed} events "
            f"(range: {inputs.start_person_id} - {inputs.end_person_id})"
        )

        return result
