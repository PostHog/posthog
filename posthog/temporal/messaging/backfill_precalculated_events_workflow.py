import os
import json
import time
import asyncio
import datetime as dt
import dataclasses
from typing import Any

import structlog
import temporalio.common
import temporalio.activity
import temporalio.workflow
import temporalio.exceptions
from structlog.contextvars import bind_contextvars

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.kafka_client.client import _KafkaProducer
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger
from posthog.temporal.messaging.filter_storage import get_event_filters
from posthog.temporal.messaging.types import BehavioralEventFilter

from common.hogvm.python.execute import BytecodeResult, execute_bytecode

LOGGER = get_logger(__name__)


def format_cohort_ids_for_logging(cohort_ids: list[int]) -> str:
    if len(cohort_ids) > 10:
        return f"More than 10... ({len(cohort_ids)} total)"
    return str(cohort_ids)


def parse_event_properties(properties_raw: Any, event_uuid: str) -> dict[str, Any]:
    """Parse event properties from ClickHouse, handling both string and dict formats."""
    if isinstance(properties_raw, str):
        try:
            parsed = json.loads(properties_raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            LOGGER.warning("Failed to parse properties for event", event_uuid=event_uuid)
            return {}
    return properties_raw if isinstance(properties_raw, dict) else {}


async def flush_kafka_batch_async(
    kafka_results: list,
    kafka_producer: _KafkaProducer,
    team_id: int,
    logger: structlog.BoundLogger,
) -> int:
    """Flush Kafka messages asynchronously and return count of successful messages."""
    if not kafka_results:
        return 0

    successful_count = len(kafka_results)
    flush_start_time = time.monotonic()
    await asyncio.to_thread(kafka_producer.flush)
    flush_duration = time.monotonic() - flush_start_time

    logger.info(
        f"Flushed batch in {flush_duration:.3f}s: {successful_count} messages",
        team_id=team_id,
        successful_messages=successful_count,
        flush_duration_seconds=flush_duration,
    )

    return successful_count


def evaluate_event_combined_filters_sync(
    combined_bytecode: list[Any],
    hog_globals: dict[str, Any],
    event_uuid: str,
) -> dict[str, Any]:
    """Execute combined bytecode for event filters, returning {condition_hash: result}."""
    try:
        bytecode_result: BytecodeResult = execute_bytecode(combined_bytecode, hog_globals)
        result = bytecode_result.result
        if isinstance(result, dict):
            return result
        return {}
    except Exception as e:
        LOGGER.warning(
            "Failed to execute combined event filter bytecode",
            event_uuid=event_uuid,
            error=str(e),
        )
        return {}


def evaluate_event_individual_filters_sync(
    filters: list[BehavioralEventFilter],
    hog_globals: dict[str, Any],
    event_uuid: str,
) -> dict[str, Any]:
    """Execute each filter's bytecode individually for error isolation."""
    results = {}
    for filter_obj in filters:
        try:
            bytecode_result: BytecodeResult = execute_bytecode(filter_obj.bytecode, hog_globals)
            result = bytecode_result.result
            if isinstance(result, bool):
                results[filter_obj.condition_hash] = result
        except Exception as e:
            LOGGER.warning(
                "Failed to execute event filter bytecode",
                event_uuid=event_uuid,
                condition_hash=filter_obj.condition_hash,
                error=str(e),
            )
    return results


def evaluate_event_filters_with_fallback_sync(
    combined_bytecode: list[Any],
    filters: list[BehavioralEventFilter],
    hog_globals: dict[str, Any],
    event_uuid: str,
) -> dict[str, Any]:
    """Execute combined bytecode with fallback to individual filter execution."""
    try:
        bytecode_result: BytecodeResult = execute_bytecode(combined_bytecode, hog_globals)
        result = bytecode_result.result

        if isinstance(result, dict):
            invalid_entries = {k: v for k, v in result.items() if not isinstance(v, bool)}
            if not invalid_entries:
                return result
            LOGGER.warning(
                "Combined event filter evaluation returned non-boolean values, falling back",
                event_uuid=event_uuid,
                invalid_condition_hashes=list(invalid_entries.keys()),
            )
    except Exception as e:
        LOGGER.info(
            "Combined event filter execution failed, falling back to individual evaluation",
            event_uuid=event_uuid,
            error=str(e),
        )

    return evaluate_event_individual_filters_sync(filters, hog_globals, event_uuid)


@dataclasses.dataclass
class BackfillPrecalculatedEventsResult:
    """Result from backfilling precalculated events for a time range."""

    events_processed: int
    events_produced: int
    events_flushed: int
    duration_seconds: float


@dataclasses.dataclass
class BackfillPrecalculatedEventsInputs:
    """Inputs for the precalculated events backfill child workflow."""

    team_id: int
    filter_storage_key: str
    cohort_ids: list[int]
    start_time: str  # ISO format datetime for the start of the time range
    end_time: str  # ISO format datetime for the end of the time range

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "cohort_count": len(self.cohort_ids),
            "cohort_ids": format_cohort_ids_for_logging(self.cohort_ids),
            "filter_storage_key": self.filter_storage_key,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


@temporalio.activity.defn
async def backfill_precalculated_events_activity(
    inputs: BackfillPrecalculatedEventsInputs,
) -> BackfillPrecalculatedEventsResult:
    """Scan events in a time range, evaluate behavioral bytecodes, and produce matching results to Kafka."""
    bind_contextvars()
    logger = LOGGER.bind(
        team_id=inputs.team_id,
        cohort_count=len(inputs.cohort_ids),
        cohort_ids=format_cohort_ids_for_logging(inputs.cohort_ids),
    )

    # Load event filters from Redis
    storage_result = await asyncio.to_thread(get_event_filters, inputs.filter_storage_key)
    if storage_result is None:
        raise temporalio.exceptions.ApplicationError(
            f"Event filters not found in storage for key: {inputs.filter_storage_key}. "
            "The Redis payload may have expired; please re-store the filters and restart the workflow.",
            type="MissingFilters",
            non_retryable=True,
        )

    filters, event_names, combined_bytecodes_by_event = storage_result
    logger.info(f"Loaded {len(filters)} event filters for {len(event_names)} event names from storage")

    if not filters:
        logger.info("No event filters found, aborting backfill")
        return BackfillPrecalculatedEventsResult(
            events_processed=0, events_produced=0, events_flushed=0, duration_seconds=0.0
        )

    # Build a lookup from event_name to its filters for fallback evaluation
    filters_by_event: dict[str, list[BehavioralEventFilter]] = {}
    for f in filters:
        filters_by_event.setdefault(f.event_name, []).append(f)

    logger.info(
        f"Starting event backfill for time range {inputs.start_time} to {inputs.end_time}, "
        f"scanning {len(event_names)} event names: {event_names}"
    )

    async with Heartbeater(
        details=(f"Processing events from {inputs.start_time} to {inputs.end_time}",)
    ) as heartbeater:
        start_time = time.time()
        kafka_producer = get_producer(topic=KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS)

        total_processed = 0
        total_events_produced = 0
        total_flushed = 0
        kafka_results: list = []
        try:
            KAFKA_FLUSH_BATCH_SIZE = int(os.environ.get("BACKFILL_EVENTS_KAFKA_FLUSH_BATCH_SIZE", "1000"))
        except ValueError:
            logger.warning("Invalid BACKFILL_EVENTS_KAFKA_FLUSH_BATCH_SIZE, using default 1000")
            KAFKA_FLUSH_BATCH_SIZE = 1000

        events_query = """
            SELECT
                uuid,
                event,
                toDate(timestamp) as date,
                distinct_id,
                person_id,
                properties
            FROM events
            WHERE team_id = %(team_id)s
              AND event IN %(event_names)s
              AND timestamp >= %(start_time)s
              AND timestamp < %(end_time)s
              AND person_id IS NOT NULL
            ORDER BY timestamp
            FORMAT JSONEachRow
        """

        query_params = {
            "team_id": inputs.team_id,
            "event_names": event_names,
            "start_time": inputs.start_time,
            "end_time": inputs.end_time,
        }

        with tags_context(
            team_id=inputs.team_id,
            feature=Feature.BEHAVIORAL_COHORTS,
            product=Product.MESSAGING,
            query_type="event_backfill",
        ):
            query_start_time = time.monotonic()
            first_row = True

            async with get_client(team_id=inputs.team_id) as client:
                async for row in client.stream_query_as_jsonl(events_query, query_parameters=query_params):
                    if first_row:
                        time_to_first = time.monotonic() - query_start_time
                        logger.info(
                            "First row received from ClickHouse",
                            time_to_first_row_seconds=round(time_to_first, 2),
                        )
                        first_row = False

                    total_processed += 1
                    event_uuid = str(row["uuid"])
                    event_name = row["event"]
                    event_date = str(row["date"])
                    distinct_id = str(row["distinct_id"])
                    person_id = str(row["person_id"])
                    event_properties = parse_event_properties(row["properties"], event_uuid)

                    # Look up the combined bytecode for this event name
                    combined_bytecode = combined_bytecodes_by_event.get(event_name)
                    event_filters = filters_by_event.get(event_name, [])

                    if not combined_bytecode and not event_filters:
                        continue

                    # Build HogVM globals for event evaluation
                    hog_globals = {"event": event_name, "properties": event_properties}

                    if combined_bytecode:
                        filter_results = await asyncio.to_thread(
                            evaluate_event_filters_with_fallback_sync,
                            combined_bytecode,
                            event_filters,
                            hog_globals,
                            event_uuid,
                        )
                    else:
                        filter_results = await asyncio.to_thread(
                            evaluate_event_individual_filters_sync,
                            event_filters,
                            hog_globals,
                            event_uuid,
                        )

                    # Produce Kafka messages for matching conditions
                    for condition_hash, matches in filter_results.items():
                        if matches:
                            try:
                                produce_result = await asyncio.to_thread(
                                    kafka_producer.produce,
                                    topic=KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS,
                                    data={
                                        "uuid": event_uuid,
                                        "team_id": inputs.team_id,
                                        "person_id": person_id,
                                        "distinct_id": distinct_id,
                                        "condition": condition_hash,
                                        "date": event_date,
                                        "source": f"cohort_event_backfill_{condition_hash}",
                                    },
                                )
                                kafka_results.append(produce_result)
                                total_events_produced += 1
                            except Exception as e:
                                logger.warning(
                                    f"Failed to produce Kafka message for event {event_uuid}: {e}",
                                    event_uuid=event_uuid,
                                    condition_hash=condition_hash,
                                    error=str(e),
                                )

                    # Periodically flush Kafka
                    if len(kafka_results) >= KAFKA_FLUSH_BATCH_SIZE:
                        batch_flushed = await flush_kafka_batch_async(
                            kafka_results, kafka_producer, inputs.team_id, logger
                        )
                        total_flushed += batch_flushed
                        kafka_results.clear()

                    # Update heartbeat periodically
                    if total_processed % 10000 == 0:
                        heartbeater.details = (
                            f"Processed {total_processed} events, produced {total_events_produced}, "
                            f"pending {len(kafka_results)} messages",
                        )

        # Final flush
        if kafka_results:
            logger.info(f"Final flush of {len(kafka_results)} Kafka results")
            final_flushed = await flush_kafka_batch_async(kafka_results, kafka_producer, inputs.team_id, logger)
            total_flushed += final_flushed

        duration_seconds = time.time() - start_time

        logger.info(
            f"Completed event backfill for {inputs.start_time} to {inputs.end_time}: "
            f"processed {total_processed} events, produced {total_events_produced}, "
            f"flushed {total_flushed} in {duration_seconds:.1f}s",
        )

        return BackfillPrecalculatedEventsResult(
            events_processed=total_processed,
            events_produced=total_events_produced,
            events_flushed=total_flushed,
            duration_seconds=duration_seconds,
        )


@temporalio.workflow.defn(name="backfill-precalculated-events")
class BackfillPrecalculatedEventsWorkflow(PostHogWorkflow):
    """Child workflow that backfills precalculated events for a single time range."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BackfillPrecalculatedEventsInputs:
        raise NotImplementedError("Use start_workflow() to trigger this workflow programmatically")

    @temporalio.workflow.run
    async def run(self, inputs: BackfillPrecalculatedEventsInputs) -> BackfillPrecalculatedEventsResult:
        workflow_logger = temporalio.workflow.logger
        workflow_logger.info(
            f"Starting event backfill for {len(inputs.cohort_ids)} cohorts "
            f"(team {inputs.team_id}, range: {inputs.start_time} to {inputs.end_time})"
        )

        result = await temporalio.workflow.execute_activity(
            backfill_precalculated_events_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(hours=12),
            heartbeat_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                maximum_attempts=3,
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(minutes=1),
            ),
        )

        workflow_logger.info(
            f"Completed event backfill: processed {result.events_processed} events, "
            f"produced {result.events_produced}, flushed {result.events_flushed} "
            f"(range: {inputs.start_time} to {inputs.end_time})"
        )

        return result
