import json
import time
import asyncio
import datetime as dt
import dataclasses
from typing import Any

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

LOGGER = get_logger(__name__)


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
    cohort_id: int
    filters: list[PersonPropertyFilter]  # Person property filters from the cohort
    batch_size: int = 1000
    offset: int = 0
    limit: int | None = None  # Total persons to process (None = all)

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "cohort_id": self.cohort_id,
            "filter_count": len(self.filters),
            "batch_size": self.batch_size,
            "offset": self.offset,
            "limit": self.limit,
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
    logger = LOGGER.bind(team_id=inputs.team_id, cohort_id=inputs.cohort_id)

    logger.info(
        f"Starting person properties precalculation for cohort {inputs.cohort_id}, "
        f"processing {inputs.limit or 'all'} persons starting at offset {inputs.offset}"
    )

    async with Heartbeater(
        details=(f"Processing persons (offset={inputs.offset}, batch_size={inputs.batch_size})",)
    ) as heartbeater:
        start_time = time.time()
        kafka_producer = KafkaProducer()

        current_offset = inputs.offset
        total_processed = 0
        total_events_produced = 0

        while True:
            # Check if we've hit the limit
            if inputs.limit is not None and total_processed >= inputs.limit:
                break

            # Calculate batch size for this iteration
            remaining = inputs.limit - total_processed if inputs.limit is not None else inputs.batch_size
            current_batch_size = min(inputs.batch_size, remaining)

            heartbeater.details = (f"Fetching batch at offset {current_offset} (batch_size={current_batch_size})",)

            # Query person table for current batch with their distinct_ids
            persons_query = """
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
                LIMIT %(limit)s
                OFFSET %(offset)s
                FORMAT JSONEachRow
            """

            query_params = {
                "team_id": inputs.team_id,
                "limit": current_batch_size,
                "offset": current_offset,
            }

            batch_count = 0
            events_to_produce = []

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

                        person_properties = parse_person_properties(row.get("properties"), person_id)
                        distinct_ids = row["distinct_ids"]

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
                                    f"Error evaluating person {person_id} against filter {filter_info.condition_hash}: {e}",
                                    person_id=person_id,
                                    condition_hash=filter_info.condition_hash,
                                    error=str(e),
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
                                    "source": f"cohort_backfill_{inputs.cohort_id}",
                                }
                                events_to_produce.append(event)

            # No more persons, we're done
            if batch_count == 0:
                break

            logger.info(f"Streamed {batch_count} persons at offset {current_offset}")

            # Produce events to Kafka in batches
            if events_to_produce:
                heartbeater.details = (f"Publishing {len(events_to_produce)} events to Kafka",)

                for event in events_to_produce:
                    await asyncio.to_thread(
                        kafka_producer.produce,
                        topic=KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES,
                        key=event["distinct_id"],
                        data=event,
                    )

                total_events_produced += len(events_to_produce)
                logger.info(f"Produced {len(events_to_produce)} events for batch at offset {current_offset}")

            total_processed += batch_count
            current_offset += batch_count

            # Update heartbeat
            heartbeater.details = (f"Processed {total_processed} persons, produced {total_events_produced} events",)

            # If we got fewer persons than batch_size, we're done
            if batch_count < current_batch_size:
                break

        end_time = time.time()
        duration_seconds = end_time - start_time

        get_person_properties_backfill_success_metric().add(1)

        logger.info(
            f"Completed person properties precalculation: processed {total_processed} persons, "
            f"produced {total_events_produced} events in {duration_seconds:.1f} seconds",
            persons_processed=total_processed,
            events_produced=total_events_produced,
            duration_seconds=duration_seconds,
        )


@temporalio.workflow.defn(name="backfill-precalculated-person-properties")
class BackfillPrecalculatedPersonPropertiesWorkflow(PostHogWorkflow):
    """Workflow that backfills precalculated person properties for a cohort."""

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
            f"Starting person properties precalculation for cohort {inputs.cohort_id} "
            f"(team {inputs.team_id}) with {len(inputs.filters)} filters"
        )

        # Process the batch of persons
        await temporalio.workflow.execute_activity(
            backfill_precalculated_person_properties_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(hours=2),  # Long timeout for large batches
            heartbeat_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                maximum_attempts=3,
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(minutes=1),
            ),
        )

        workflow_logger.info("Precalculated person properties backfill workflow completed")
