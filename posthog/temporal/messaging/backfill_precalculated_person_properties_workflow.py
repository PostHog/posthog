import os
import json
import time
import asyncio
import datetime as dt
import dataclasses
from typing import TYPE_CHECKING, Any

import structlog
import temporalio.common
import temporalio.activity
import temporalio.workflow
import temporalio.exceptions
from structlog.contextvars import bind_contextvars

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.kafka_client.client import _KafkaProducer
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger
from posthog.temporal.messaging.filter_storage import get_filters_and_properties
from posthog.temporal.messaging.types import PersonPropertyFilter

from common.hogvm.python.execute import BytecodeResult, execute_bytecode

if TYPE_CHECKING:
    pass

LOGGER = get_logger(__name__)
MAX_OPTIMIZED_PROPERTIES = 100  # Safety limit to avoid query complexity issues


def build_person_properties_select_clause(person_properties: list[str]) -> tuple[str, dict[str, str], dict[str, str]]:
    """Build ClickHouse SELECT expressions for the requested person properties.

    Property names come from cohort filters, so they must stay out of the SQL string.
    The returned clause contains only generated aliases and query parameter placeholders.
    """
    property_selects: list[str] = []
    property_alias_mapping: dict[str, str] = {}
    property_query_params: dict[str, str] = {}

    for i, prop in enumerate(person_properties):
        safe_alias = f"prop_{i}"
        property_key_param = f"property_key_{i}"
        property_selects.append(f"JSONExtract(properties, %({property_key_param})s, 'String') as `{safe_alias}`")
        property_alias_mapping[safe_alias] = prop
        property_query_params[property_key_param] = prop

    return ",\n                ".join(property_selects), property_alias_mapping, property_query_params


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
    kafka_producer: _KafkaProducer,
    team_id: int,
    logger: structlog.BoundLogger,
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
    person_id: str | None = None  # Optional specific person ID to filter for
    single_cohort_mode: bool = False  # True when --cohort-id was explicitly provided

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


def evaluate_combined_filters_sync(
    combined_bytecode: list[Any],
    hog_globals: dict[str, Any],
    person_id: str,
    detailed_logging: bool = False,
) -> dict[str, Any]:
    """Execute combined bytecode for all filters, returning {condition_hash: result}.

    Returns empty dict on error so the person is skipped without crashing the activity.
    """
    try:
        bytecode_result: BytecodeResult = execute_bytecode(combined_bytecode, hog_globals)
        result = bytecode_result.result

        if detailed_logging:
            LOGGER.info(
                "HogVM evaluation completed",
                person_id=person_id,
                result=result,
                result_type=type(result).__name__,
                person_properties=hog_globals.get("person", {}).get("properties", {}),
                execution_successful=True,
                execution_stdout=bytecode_result.stdout,
            )

        if isinstance(result, dict):
            return result

        if detailed_logging:
            LOGGER.warning(
                "HogVM evaluation returned non-dict result",
                person_id=person_id,
                result=result,
                result_type=type(result).__name__,
            )

        return {}
    except Exception as e:
        LOGGER.warning(
            "Failed to execute combined filter bytecode for person",
            person_id=person_id,
            error=str(e),
        )
        return {}


def evaluate_individual_filters_sync(
    filters: list[PersonPropertyFilter],
    hog_globals: dict[str, Any],
    person_id: str,
    detailed_logging: bool = False,
) -> dict[str, Any]:
    """Execute each filter's bytecode individually, returning {condition_hash: result}.

    Isolates failures to individual cohorts rather than failing all cohorts for a person.
    Returns results for successful filters only; failed filters are omitted from results.
    """
    results = {}

    for filter_obj in filters:
        try:
            bytecode_result: BytecodeResult = execute_bytecode(filter_obj.bytecode, hog_globals)
            result = bytecode_result.result

            if detailed_logging:
                LOGGER.info(
                    "Individual filter evaluation completed",
                    person_id=person_id,
                    condition_hash=filter_obj.condition_hash,
                    result=result,
                    result_type=type(result).__name__,
                    execution_successful=True,
                    execution_stdout=bytecode_result.stdout,
                )

            # Store the result for this specific condition
            if isinstance(result, bool):
                results[filter_obj.condition_hash] = result
            elif detailed_logging:
                LOGGER.warning(
                    "Individual filter evaluation returned non-bool result",
                    person_id=person_id,
                    condition_hash=filter_obj.condition_hash,
                    result=result,
                    result_type=type(result).__name__,
                )
        except Exception as e:
            LOGGER.warning(
                "Failed to execute filter bytecode for person",
                person_id=person_id,
                condition_hash=filter_obj.condition_hash,
                cohort_ids=filter_obj.cohort_ids,
                error=str(e),
            )

    return results


def evaluate_combined_filters_with_fallback_sync(
    combined_bytecode: list[Any],
    filters: list[PersonPropertyFilter],
    hog_globals: dict[str, Any],
    person_id: str,
    detailed_logging: bool = False,
) -> dict[str, Any]:
    """Execute combined bytecode with fallback to individual filter execution.

    First attempts to execute all filters in a single combined bytecode for performance.
    If that fails, falls back to executing each filter individually to isolate failures.
    """
    # First, try the fast path with combined bytecode
    try:
        bytecode_result: BytecodeResult = execute_bytecode(combined_bytecode, hog_globals)
        result = bytecode_result.result

        if detailed_logging:
            LOGGER.info(
                "Combined filter evaluation completed successfully",
                person_id=person_id,
                result=result,
                result_type=type(result).__name__,
                person_properties=hog_globals.get("person", {}).get("properties", {}),
                execution_successful=True,
                execution_stdout=bytecode_result.stdout,
            )

        if isinstance(result, dict):
            invalid_result_entries = {
                condition_hash: value for condition_hash, value in result.items() if not isinstance(value, bool)
            }
            if not invalid_result_entries:
                return result
            LOGGER.warning(
                "Combined filter evaluation returned non-boolean values, falling back to individual execution",
                person_id=person_id,
                invalid_condition_hashes=list(invalid_result_entries.keys()),
                invalid_result_types={
                    condition_hash: type(value).__name__ for condition_hash, value in invalid_result_entries.items()
                },
            )

        if detailed_logging:
            LOGGER.warning(
                "Combined filter evaluation returned non-dict result, falling back to individual execution",
                person_id=person_id,
                result=result,
                result_type=type(result).__name__,
            )
    except Exception as e:
        LOGGER.info(
            "Combined filter execution failed, falling back to individual filter evaluation",
            person_id=person_id,
            error=str(e),
            fallback_reason="combined_execution_failed",
        )

    # Fallback to individual filter execution for error isolation
    return evaluate_individual_filters_sync(filters, hog_globals, person_id, detailed_logging)


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

    # Load filters, person properties, and combined bytecode from Redis storage without blocking the event loop
    storage_result = await asyncio.to_thread(get_filters_and_properties, inputs.filter_storage_key)
    if storage_result is None:
        raise temporalio.exceptions.ApplicationError(
            f"Filters not found in storage for key: {inputs.filter_storage_key}. "
            "The Redis payload may have expired; please re-store the filters and restart the workflow.",
            type="MissingFilters",
            non_retryable=True,
        )

    filters, person_properties, combined_bytecode = storage_result
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

    # Enable detailed logging when both cohort_id and person_id are set (single cohort + single person mode)
    detailed_logging_enabled = inputs.person_id is not None and inputs.single_cohort_mode

    async with Heartbeater(
        details=(f"Processing persons from {inputs.start_person_id} to {inputs.end_person_id}",)
    ) as heartbeater:
        start_time = time.time()
        kafka_producer = get_producer(topic=KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES)

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
        property_alias_mapping: dict[str, str] = {}
        property_query_params: dict[str, str] = {}

        if person_properties and len(person_properties) <= MAX_OPTIMIZED_PROPERTIES:
            properties_clause, property_alias_mapping, property_query_params = build_person_properties_select_clause(
                person_properties
            )

            logger.info(
                f"Optimized query: fetching {len(person_properties)} specific properties with parameterized keys"
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

        person_filter_clause = "AND id = %(person_id)s" if inputs.person_id is not None else ""
        persons_query = f"""
            SELECT
                id as person_id,
                {properties_clause}
            FROM person FINAL
            WHERE team_id = %(team_id)s
              AND id >= %(start_person_id)s
              AND id <= %(end_person_id)s
              AND is_deleted = 0
              {person_filter_clause}
            ORDER BY id
            FORMAT JSONEachRow
        """

        query_params = {
            "team_id": inputs.team_id,
            "start_person_id": inputs.start_person_id,
            "end_person_id": inputs.end_person_id,
            **property_query_params,
        }
        if inputs.person_id is not None:
            query_params["person_id"] = inputs.person_id

        last_person_id = inputs.start_person_id
        batch_count = 0

        logger.info("Starting ClickHouse client connection and query execution")

        with tags_context(
            team_id=inputs.team_id,
            feature=Feature.BEHAVIORAL_COHORTS,
            product=Product.MESSAGING,
            query_type="person_properties_backfill",
        ):
            logger.info("Acquiring ClickHouse client connection", team_id=inputs.team_id)
            async with get_client(team_id=inputs.team_id) as client:
                logger.info(
                    "ClickHouse client connection established, starting query execution",
                    team_id=inputs.team_id,
                    query=persons_query,
                    query_params=query_params,
                )
                # Time the ClickHouse query execution
                query_start_time = time.monotonic()

                first_row = True
                async for row in client.stream_query_as_jsonl(persons_query, query_parameters=query_params):
                    if first_row:
                        query_first_row_time = time.monotonic()
                        logger.info(
                            "First row received from ClickHouse query",
                            team_id=inputs.team_id,
                            time_to_first_row_seconds=round(query_first_row_time - query_start_time, 2),
                            first_person_id=str(row["person_id"]),
                        )
                        first_row = False
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

                    # Evaluate all filters in a single VM call
                    person_filter_start = time.monotonic()
                    hog_globals = {"person": {"properties": parsed_properties}}

                    filter_results = await asyncio.to_thread(
                        evaluate_combined_filters_with_fallback_sync,
                        combined_bytecode,
                        filters,
                        hog_globals,
                        person_id,
                        detailed_logging=detailed_logging_enabled,
                    )

                    # Detailed logging for filter results when in single cohort + single person mode
                    if detailed_logging_enabled:
                        person_filter_duration = time.monotonic() - person_filter_start
                        matching_conditions = [
                            condition_hash for condition_hash, matches in filter_results.items() if matches
                        ]
                        logger.info(
                            "Filter evaluation results",
                            person_id=person_id,
                            total_conditions=len(filter_results),
                            matching_conditions=len(matching_conditions),
                            matching_condition_hashes=matching_conditions,
                            all_results=filter_results,
                            evaluation_duration_ms=round(person_filter_duration * 1000, 2),
                            person_properties_count=len(parsed_properties),
                        )

                    # Produce Kafka messages for matching conditions
                    for condition_hash, matches in filter_results.items():
                        if matches:
                            try:
                                produce_result = kafka_producer.produce(
                                    topic=KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES,
                                    data={
                                        "team_id": inputs.team_id,
                                        "distinct_id": person_id,
                                        "person_id": person_id,
                                        "condition": condition_hash,
                                        "matches": matches,
                                        "source": f"cohort_filter_{condition_hash}",
                                    },
                                )
                                kafka_results.append(produce_result)
                                total_events_produced += 1

                                if detailed_logging_enabled:
                                    logger.info(
                                        "Kafka message produced for matching condition",
                                        person_id=person_id,
                                        condition_hash=condition_hash,
                                        matches=matches,
                                        kafka_topic=KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES,
                                    )
                            except Exception as e:
                                logger.warning(
                                    f"Failed to produce Kafka message for person {person_id}: {e}",
                                    person_id=person_id,
                                    condition_hash=condition_hash,
                                    error=str(e),
                                )

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
