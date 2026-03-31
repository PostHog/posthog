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
from posthog.temporal.common.client import async_connect
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


async def evaluate_single_filter_async(filter_obj, globals_dict):
    """Async wrapper for single filter evaluation."""
    return await asyncio.to_thread(execute_bytecode, filter_obj.bytecode, globals_dict, timeout=10)


async def evaluate_person_against_all_filters(person_id, parsed_properties, filters, inputs, logger):
    """Evaluate one person against all filters concurrently.

    Args:
        person_id: The person ID
        parsed_properties: Parsed person properties dict
        filters: List of filter objects to evaluate
        inputs: Process inputs containing team_id
        logger: Logger instance with bound context

    Returns:
        List of events for this person (one per filter)
    """
    # Create all evaluation tasks concurrently
    evaluation_tasks = []
    for filter_obj in filters:
        # Create a separate globals_dict for each task to avoid thread safety issues
        local_globals = {
            "person": {
                "id": person_id,
                "properties": parsed_properties,
            },
            "project": {
                "id": inputs.team_id,
            },
        }
        task = asyncio.create_task(evaluate_single_filter_async(filter_obj, local_globals))
        evaluation_tasks.append((task, filter_obj))

    # Wait for all evaluations to complete concurrently
    events = []
    results = await asyncio.gather(*[task for task, _ in evaluation_tasks], return_exceptions=True)

    # Process results
    for (_task, filter_obj), result in zip(evaluation_tasks, results):
        if isinstance(result, Exception):
            # Use the passed logger with bound context
            logger.debug(
                f"Error evaluating person {person_id} against filter {filter_obj.condition_hash}: {result}",
                person_id=person_id,
                condition_hash=filter_obj.condition_hash,
                error=str(result),
            )
            matches = False
        else:
            matches = (
                bool(result.result)
                if hasattr(result, "result") and result and not isinstance(result, BaseException)
                else False
            )

        # Create event for this filter result
        event = {
            "distinct_id": person_id,
            "person_id": person_id,
            "team_id": inputs.team_id,
            "condition": filter_obj.condition_hash,
            "matches": matches,
            "source": f"cohort_backfill_{filter_obj.condition_hash}",
        }
        events.append(event)

    return events


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
    kafka_futures: list, kafka_producer, team_id: int, logger, flush_duration_metric=None
) -> int:
    """Flush a batch of Kafka futures concurrently without blocking producer.

    Args:
        kafka_futures: List of futures from Kafka produce operations
        team_id: Team ID for logging and metrics
        logger: Logger instance
        flush_duration_metric: Optional metric to record flush duration

    Returns:
        Number of messages successfully flushed
    """
    if not kafka_futures:
        return 0

    batch_size = len(kafka_futures)
    logger.info(f"Flushing batch of {batch_size} Kafka futures", team_id=team_id, batch_size=batch_size)

    # Time the async flush operation
    flush_start_time = time.monotonic()

    try:
        # Wait for all futures to complete
        results = await asyncio.gather(*kafka_futures, return_exceptions=True)

        # Actually flush messages to Kafka brokers
        await asyncio.to_thread(kafka_producer.flush)

        # Count successful sends
        successful_sends = 0
        failed_sends = 0

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed_sends += 1
                logger.debug(f"Kafka future {i} failed: {result}", team_id=team_id)
            else:
                successful_sends += 1

        flush_duration = time.monotonic() - flush_start_time

        # Record flush performance metrics if metric is provided
        if flush_duration_metric:
            flush_duration_metric.record(flush_duration, {"team_id": str(team_id)})

        logger.info(
            f"Async flush completed: {successful_sends} successful, {failed_sends} failed in {flush_duration:.3f}s",
            team_id=team_id,
            successful_sends=successful_sends,
            failed_sends=failed_sends,
            flush_duration_seconds=flush_duration,
        )

        return successful_sends

    except Exception as e:
        flush_duration = time.monotonic() - flush_start_time
        logger.exception(
            f"Async Kafka flush failed after {flush_duration:.3f}s",
            team_id=team_id,
            batch_size=batch_size,
            error=str(e),
        )
        raise


@temporalio.activity.defn
async def start_next_workflow_activity(inputs, workflow_id: str) -> None:
    """Activity to start the next workflow in the pipeline."""
    from django.conf import settings

    import structlog

    logger = structlog.get_logger(__name__)

    try:
        logger.info(f"Starting next workflow in pipeline: {workflow_id}")
        client = await async_connect()
        handle = await client.start_workflow(
            BackfillPrecalculatedPersonPropertiesWorkflow.run,
            inputs,
            id=workflow_id,
            task_queue=settings.MESSAGING_TASK_QUEUE,
            execution_timeout=dt.timedelta(hours=24),
        )
        logger.info(f"Successfully started workflow: {handle.id}")
    except Exception as e:
        logger.exception(f"Failed to start workflow {workflow_id}: {e}")
        raise


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
    cursor: str = "00000000-0000-0000-0000-000000000000"  # UUID cursor for pagination
    batch_sequence: int = 1  # Sequence number for this batch in the pipeline

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "cohort_count": len(self.cohort_ids),
            "cohort_ids": format_cohort_ids_for_logging(self.cohort_ids),
            "filter_storage_key": self.filter_storage_key,
            "batch_size": self.batch_size,
            "cursor": self.cursor,
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
        f"processing {len(filters)} total filters from cursor {inputs.cursor} "
        f"with batch size {inputs.batch_size} ({len(filters)} filters = ~{inputs.batch_size * len(filters)} events per batch)"
    )

    async with Heartbeater(details=(f"Processing persons from {inputs.cursor}",)) as heartbeater:
        start_time = time.time()
        kafka_producer = KafkaProducer()

        total_processed = 0
        total_events_produced = 0
        total_flushed = 0
        kafka_batch_offset = 0  # Track kafka batch number, not person count
        # Configure Kafka flush batch size via environment variable
        try:
            FLUSH_BATCH_SIZE = int(os.environ.get("BACKFILL_KAFKA_FLUSH_BATCH_SIZE", "10000"))
            if FLUSH_BATCH_SIZE <= 0:
                logger.warning(
                    f"Invalid BACKFILL_KAFKA_FLUSH_BATCH_SIZE={FLUSH_BATCH_SIZE}, using default 10000",
                    team_id=inputs.team_id,
                )
                FLUSH_BATCH_SIZE = 10000
        except ValueError:
            logger.warning(
                f"Invalid BACKFILL_KAFKA_FLUSH_BATCH_SIZE={os.environ.get('BACKFILL_KAFKA_FLUSH_BATCH_SIZE')}, using default 10000",
                team_id=inputs.team_id,
            )
            FLUSH_BATCH_SIZE = 10000

        kafka_futures = []  # Store async futures for later flushing
        pending_flush_tasks = []  # Store background flush tasks

        # Create metric once for activity
        flush_duration_metric = None
        try:
            metric_meter = temporalio.activity.metric_meter()
            flush_duration_metric = metric_meter.create_histogram_float(
                "backfill_kafka_flush_duration_seconds", "Duration of Kafka flush operations in seconds", unit="seconds"
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
              AND id > %(cursor)s
              AND is_deleted = 0
            ORDER BY id
            LIMIT %(batch_size)s
            FORMAT JSONEachRow
        """

        query_params = {
            "team_id": inputs.team_id,
            "cursor": inputs.cursor,
            "batch_size": inputs.batch_size,
        }

        last_person_id = inputs.cursor
        batch_count = 0

        with tags_context(
            team_id=inputs.team_id,
            feature=Feature.BEHAVIORAL_COHORTS,
            product=Product.MESSAGING,
            query_type="person_properties_backfill",
        ):
            async with get_client(team_id=inputs.team_id) as client:
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

                    # Evaluate all filters for this person concurrently
                    person_events = await evaluate_person_against_all_filters(
                        person_id, parsed_properties, filters, inputs, logger
                    )

                    # Process all events from this person
                    for event in person_events:
                        # Produce to Kafka and collect futures for async flushing
                        try:
                            # Create async future for Kafka produce
                            future = asyncio.create_task(
                                asyncio.to_thread(
                                    kafka_producer.produce,
                                    topic=KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES,
                                    data=event,
                                )
                            )
                            kafka_futures.append(future)
                            total_events_produced += 1

                            # Start background flush every 10K messages, but don't await
                            if len(kafka_futures) >= FLUSH_BATCH_SIZE:
                                # Start background flush task
                                flush_task = asyncio.create_task(
                                    flush_kafka_batch_async(
                                        kafka_futures[:FLUSH_BATCH_SIZE],  # Copy current batch
                                        kafka_producer,
                                        inputs.team_id,
                                        logger,
                                        flush_duration_metric,
                                    )
                                )
                                pending_flush_tasks.append(flush_task)
                                kafka_batch_offset += 1

                                # Keep remaining futures for next batch
                                kafka_futures = kafka_futures[FLUSH_BATCH_SIZE:]

                                logger.info(
                                    f"Started background flush task {len(pending_flush_tasks)} for batch {kafka_batch_offset}",
                                    team_id=inputs.team_id,
                                    kafka_batch_offset=kafka_batch_offset,
                                )

                        except Exception as e:
                            logger.warning(
                                f"Failed to produce Kafka message for distinct_id {event['distinct_id']}: {e}",
                                distinct_id=event["distinct_id"],
                                person_id=person_id,
                                error=str(e),
                            )
                            # Continue processing even if Kafka produce fails

        logger.info(f"Processed {batch_count} persons from {inputs.cursor} to {last_person_id}")
        total_processed = batch_count

        # Update heartbeat
        heartbeater.details = (
            f"Processed {total_processed} persons, produced {total_events_produced} events, flushed {total_flushed}",
        )

        # Await all background flush tasks and handle remaining futures
        logger.info(
            f"Awaiting {len(pending_flush_tasks)} background flush tasks and {len(kafka_futures)} remaining futures",
            team_id=inputs.team_id,
        )

        # Await all background flush tasks
        if pending_flush_tasks:
            flush_results = await asyncio.gather(*pending_flush_tasks, return_exceptions=True)
            for i, result in enumerate(flush_results):
                if isinstance(result, Exception):
                    logger.exception(f"Background flush task {i} failed: {result}", team_id=inputs.team_id)
                elif isinstance(result, int):
                    total_flushed += result
                    logger.info(f"Background flush task {i} completed: {result} messages", team_id=inputs.team_id)

        # Flush any remaining futures
        if kafka_futures:
            logger.info(f"Final flush of {len(kafka_futures)} remaining futures", team_id=inputs.team_id)
            final_flushed = await flush_kafka_batch_async(
                kafka_futures,
                kafka_producer,
                inputs.team_id,
                logger,
                flush_duration_metric,
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
        """Run the workflow to backfill precalculated person properties with pipeline chaining."""
        workflow_logger = temporalio.workflow.logger
        cohort_ids = inputs.cohort_ids
        workflow_logger.info(
            f"Starting person properties precalculation for {len(cohort_ids)} cohorts {format_cohort_ids_for_logging(cohort_ids)} "
            f"(team {inputs.team_id}, cursor: {inputs.cursor})"
        )

        workflow_logger.info(f"Processing batch with cursor: {inputs.cursor}")

        # Process the current batch first to determine if there are more persons
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

        # Start next workflow if current batch was full (indicating more data)
        if result.persons_processed >= inputs.batch_size and result.last_person_id:
            try:
                # Create next batch inputs with incremented sequence
                next_sequence = inputs.batch_sequence + 1
                next_inputs = dataclasses.replace(inputs, cursor=result.last_person_id, batch_sequence=next_sequence)

                workflow_logger.info(
                    f"Starting next workflow in pipeline for cursor: {result.last_person_id}, batch: {next_sequence}"
                )

                # Generate workflow ID using batch sequence
                base_id = temporalio.workflow.info().workflow_id
                if "-batch-" in base_id:
                    base_id = base_id.rsplit("-batch-", 1)[0]
                workflow_id = f"{base_id}-batch-{next_sequence}"

                await temporalio.workflow.execute_activity(
                    start_next_workflow_activity,
                    args=[next_inputs, workflow_id],
                    start_to_close_timeout=dt.timedelta(minutes=5),
                )

                workflow_logger.info(f"Next workflow started with ID: {workflow_id}")

            except Exception as e:
                workflow_logger.exception(
                    f"Failed to start next workflow in pipeline: {e}. "
                    f"Next cursor would have been: {result.last_person_id}. "
                    f"This will stop the pipeline and skip remaining persons!"
                )
                # Raise the exception to surface the failure instead of silently stopping
                raise

        workflow_logger.info(
            f"Precalculated person properties backfill workflow completed: "
            f"processed {result.persons_processed} persons, last_id: {result.last_person_id}"
        )

        return result
