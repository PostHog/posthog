import json
import time
import asyncio
import datetime as dt
import dataclasses
from typing import TYPE_CHECKING, Any

import temporalio.activity
import temporalio.workflow
from structlog.contextvars import bind_contextvars

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

from common.hogvm.python.execute import execute_bytecode

if TYPE_CHECKING:
    from posthog.kafka_client.client import _KafkaProducer

LOGGER = get_logger(__name__)

HEARTBEAT_LOG_FREQUENCY = 10_000


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


async def flush_kafka_batch(
    kafka_producer: "_KafkaProducer",
    pending_messages: list,
    team_id: int,
    persons_processed: int,
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
    heartbeater.details = (f"Flushing {batch_type}{batch_size} messages (processed {persons_processed} persons)",)
    logger.info(
        f"Flushing {batch_type}batch of {batch_size} messages",
        team_id=team_id,
        persons_processed=persons_processed,
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
                f"Kafka send result failure: {e}",
                team_id=team_id,
                persons_processed=persons_processed,
                error=str(e),
                exception_type=type(e).__name__,
            )
            failed_count += 1

    if failed_count > 0:
        logger.error(
            f"Failed to send {failed_count}/{batch_size} Kafka messages",
            team_id=team_id,
            persons_processed=persons_processed,
            failed_count=failed_count,
            batch_size=batch_size,
        )
        raise Exception(f"Failed to send {failed_count}/{batch_size} Kafka messages")

    return batch_size


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
class PersonPropertyFilter:
    """Person property filter to evaluate."""

    condition_hash: str
    bytecode: list[Any]  # HogQL bytecode


@dataclasses.dataclass
class BackfillPrecalculatedPersonPropertiesInputs:
    """Inputs for the precalculated person properties backfill workflow."""

    team_id: int
    filters: list[PersonPropertyFilter]  # Deduplicated person property filters
    batch_size: int = 1000
    min_person_id: str | None = None  # UUID range start (inclusive)
    max_person_id: str | None = None  # UUID range end (exclusive)

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "filter_count": len(self.filters),
            "batch_size": self.batch_size,
            "min_person_id": self.min_person_id,
            "max_person_id": self.max_person_id,
        }


@temporalio.activity.defn
async def backfill_precalculated_person_properties_activity(
    inputs: BackfillPrecalculatedPersonPropertiesInputs,
) -> None:
    """
    Backfill precalculated person properties for a batch of persons.

    Queries the current state of persons from the persons table and evaluates them
    against the provided filters, writing results to the precalculated_person_properties table.
    """
    bind_contextvars()
    logger = LOGGER.bind(team_id=inputs.team_id, filter_count=len(inputs.filters))

    logger.info(
        f"Starting person properties precalculation for team {inputs.team_id} "
        f"({len(inputs.filters)} unique conditions), "
        f"processing persons in UUID range [{inputs.min_person_id or 'MIN'}, {inputs.max_person_id or 'MAX'})"
    )

    async with Heartbeater(
        details=(
            f"Processing persons (uuid_range=[{inputs.min_person_id or 'MIN'}, {inputs.max_person_id or 'MAX'}), batch_size={inputs.batch_size})",
        )
    ) as heartbeater:
        start_time = time.time()
        kafka_producer = KafkaProducer()

        total_processed = 0
        total_events_produced = 0
        total_flushed = 0
        FLUSH_BATCH_SIZE = 10_000  # Flush every 10k messages to allow heartbeats
        pending_kafka_messages = []

        # Build UUID range filter if provided
        uuid_filter_clauses = []
        if inputs.min_person_id is not None:
            uuid_filter_clauses.append("AND id >= %(min_person_id)s")
        if inputs.max_person_id is not None:
            uuid_filter_clauses.append("AND id < %(max_person_id)s")
        uuid_filter = " ".join(uuid_filter_clauses)

        heartbeater.details = (
            f"Streaming persons in UUID range [{inputs.min_person_id or 'MIN'}, {inputs.max_person_id or 'MAX'})",
        )

        # Query person table for all persons in UUID range with their distinct_ids
        persons_query = f"""
            SELECT
                p.person_id,
                p.properties,
                pdi.distinct_ids
            FROM (
                SELECT
                    id as person_id,
                    argMax(properties, version) as properties
                FROM person
                WHERE team_id = %(team_id)s
                {uuid_filter}
                GROUP BY id
                HAVING argMax(is_deleted, version) = 0
            ) p
            INNER JOIN (
                SELECT
                    person_id,
                    groupArray(distinct_id) as distinct_ids
                FROM (
                    SELECT
                        argMax(person_id, version) as person_id,
                        distinct_id
                    FROM person_distinct_id2
                    WHERE team_id = %(team_id)s
                    GROUP BY distinct_id
                    HAVING argMax(is_deleted, version) = 0
                )
                GROUP BY person_id
            ) pdi ON p.person_id = pdi.person_id
            ORDER BY p.person_id
            FORMAT JSONEachRow
        """

        query_params: dict[str, Any] = {"team_id": inputs.team_id}
        if inputs.min_person_id is not None:
            query_params["min_person_id"] = inputs.min_person_id
        if inputs.max_person_id is not None:
            query_params["max_person_id"] = inputs.max_person_id

        # Stream all persons in the UUID range
        with tags_context(
            team_id=inputs.team_id,
            feature=Feature.BEHAVIORAL_COHORTS,
            product=Product.MESSAGING,
            query_type="person_properties_backfill",
        ):
            async with get_client(team_id=inputs.team_id) as client:
                async for row in client.stream_query_as_jsonl(persons_query, query_parameters=query_params):
                    total_processed += 1
                    person_id = str(row["person_id"])

                    person_properties = parse_person_properties(row.get("properties"), person_id)
                    distinct_ids = row["distinct_ids"]

                    # Evaluate person against ALL filters (deduplicated conditions)
                    for filter_info in inputs.filters:
                        # Evaluate person against filter using HogQL bytecode
                        globals_dict = {
                            "person": {
                                "id": person_id,
                                "properties": person_properties,
                            },
                            "project": {
                                "id": inputs.team_id,
                            },
                        }

                        try:
                            result = await asyncio.to_thread(
                                execute_bytecode, filter_info.bytecode, globals_dict, timeout=10
                            )
                            matches = bool(result.result) if result else False
                        except Exception as e:
                            logger.warning(
                                f"Filter evaluation error: {type(e).__name__}",
                                person_id=person_id,
                                condition_hash=filter_info.condition_hash,
                            )
                            matches = False

                        # ALWAYS emit - both matches and non-matches for EACH distinct_id
                        for distinct_id in distinct_ids:
                            event = {
                                "distinct_id": distinct_id,
                                "person_id": person_id,
                                "team_id": inputs.team_id,
                                "condition": filter_info.condition_hash,
                                "matches": matches,
                                "source": f"cohort_backfill_{filter_info.condition_hash}",
                            }

                            # Produce to Kafka without blocking - collect send results for later flushing
                            try:
                                send_result = kafka_producer.produce(
                                    topic=KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES,
                                    key=event["distinct_id"],
                                    data=event,
                                )
                                pending_kafka_messages.append(send_result)
                                total_events_produced += 1

                                # Flush in batches to allow heartbeats
                                if len(pending_kafka_messages) >= FLUSH_BATCH_SIZE:
                                    flushed = await flush_kafka_batch(
                                        kafka_producer,
                                        pending_kafka_messages,
                                        inputs.team_id,
                                        total_processed,
                                        heartbeater,
                                        logger,
                                    )
                                    total_flushed += flushed
                                    pending_kafka_messages.clear()

                            except Exception as e:
                                logger.warning(
                                    f"Failed to produce Kafka message for distinct_id {event['distinct_id']}: {e}",
                                    distinct_id=event["distinct_id"],
                                    person_id=person_id,
                                    error=str(e),
                                )
                                # Continue processing even if Kafka produce fails

                    # Update heartbeat periodically
                    if total_processed % HEARTBEAT_LOG_FREQUENCY == 0:
                        heartbeater.details = (
                            f"Processed {total_processed} persons, produced {total_events_produced} events, flushed {total_flushed}",
                        )
                        logger.info(
                            f"Progress: {total_processed} persons processed, {total_events_produced} events produced"
                        )

        # Flush any remaining messages
        if pending_kafka_messages:
            flushed = await flush_kafka_batch(
                kafka_producer,
                pending_kafka_messages,
                inputs.team_id,
                total_processed,
                heartbeater,
                logger,
                is_final=True,
            )
            total_flushed += flushed
            pending_kafka_messages.clear()

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


@temporalio.workflow.defn(name="backfill-precalculated-person-properties")
class BackfillPrecalculatedPersonPropertiesWorkflow(PostHogWorkflow):
    """Workflow that backfills precalculated person properties for a team's cohorts."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BackfillPrecalculatedPersonPropertiesInputs:
        """Parse inputs from the management command CLI."""
        # This would be called programmatically, not from CLI
        raise NotImplementedError("Use start_workflow() to trigger this workflow programmatically")

    @temporalio.workflow.run
    async def run(self, inputs: BackfillPrecalculatedPersonPropertiesInputs) -> None:
        """Run the workflow to backfill precalculated person properties."""
        workflow_logger = temporalio.workflow.logger
        workflow_logger.info(
            f"Starting person properties precalculation for team {inputs.team_id} "
            f"({len(inputs.filters)} unique conditions) in UUID range "
            f"[{inputs.min_person_id or 'MIN'}, {inputs.max_person_id or 'MAX'})"
        )

        # Process the batch of persons
        await temporalio.workflow.execute_activity(
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

        workflow_logger.info("Precalculated person properties backfill workflow completed")
