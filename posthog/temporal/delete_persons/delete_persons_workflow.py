import json
import typing
import asyncio
import datetime as dt
import dataclasses

from django.conf import settings

import psycopg
import temporalio.common
import temporalio.activity
import temporalio.workflow
from structlog import get_logger

from posthog.clickhouse.query_tagging import tag_queries
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater

LOGGER = get_logger(__name__)

SELECT_QUERY = """
    SELECT id
    FROM posthog_person
    WHERE team_id=%(team_id)s {person_ids_filter}
    ORDER BY id ASC
    LIMIT %(limit)s
"""

DELETE_QUERY_PERSON_DISTINCT_IDS = """
    WITH to_delete AS ({select_query})
    DELETE FROM posthog_persondistinctid
    WHERE person_id IN (SELECT id FROM to_delete);
"""

DELETE_QUERY_PERSON_OVERRIDE = """
    WITH to_delete AS ({select_query})
    DELETE FROM posthog_personoverride
    WHERE (old_person_id IN (SELECT id FROM to_delete) OR override_person_id IN (SELECT id FROM to_delete));
"""

DELETE_QUERY_COHORT_PEOPLE = """
    WITH to_delete AS ({select_query})
    DELETE FROM posthog_cohortpeople
    WHERE person_id IN (SELECT id FROM to_delete);
"""

DELETE_QUERY_PERSON = """
    WITH to_delete AS ({select_query})
    DELETE FROM posthog_person
    WHERE id IN (SELECT id FROM to_delete);
"""


@dataclasses.dataclass
class MogrifyDeleteQueriesActivityInputs:
    """Inputs for the `mogrify_delete_queries_activity`."""

    team_id: int
    person_ids: list[int] = dataclasses.field(default_factory=list)
    batch_size: int = 1000

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "batch_size": self.batch_size,
        }


@temporalio.activity.defn
async def mogrify_delete_queries_activity(inputs: MogrifyDeleteQueriesActivityInputs) -> None:
    """Mogrify and log queries to delete persons and associated entities."""
    async with Heartbeater():
        logger = LOGGER.bind()

        select_query = SELECT_QUERY.format(
            person_ids_filter=f"AND id IN {tuple(inputs.person_ids)}" if inputs.person_ids else ""
        )
        delete_query_person_distinct_ids = DELETE_QUERY_PERSON_DISTINCT_IDS.format(select_query=select_query)
        delete_query_person_override = DELETE_QUERY_PERSON_OVERRIDE.format(select_query=select_query)
        delete_query_cohort_people = DELETE_QUERY_COHORT_PEOPLE.format(select_query=select_query)
        delete_query_person = DELETE_QUERY_PERSON.format(select_query=select_query)

        conn = await psycopg.AsyncConnection.connect(settings.DATABASE_URL)
        conn.cursor_factory = psycopg.AsyncClientCursor
        async with conn:
            async with conn.cursor() as cursor:
                cursor = typing.cast(psycopg.AsyncClientCursor, cursor)

                prepared_person_distinct_ids_query = cursor.mogrify(
                    delete_query_person_distinct_ids,
                    {"team_id": inputs.team_id, "limit": inputs.batch_size, "person_ids": inputs.person_ids},
                )
                prepared_person_override_query = cursor.mogrify(
                    delete_query_person_override,
                    {"team_id": inputs.team_id, "limit": inputs.batch_size, "person_ids": inputs.person_ids},
                )
                prepared_cohort_people_query = cursor.mogrify(
                    delete_query_cohort_people,
                    {"team_id": inputs.team_id, "limit": inputs.batch_size, "person_ids": inputs.person_ids},
                )
                prepared_person_query = cursor.mogrify(
                    delete_query_person,
                    {"team_id": inputs.team_id, "limit": inputs.batch_size, "person_ids": inputs.person_ids},
                )
        logger.info("Delete query for person distinct ids: %s", prepared_person_distinct_ids_query)
        logger.info("Delete query for person overrides: %s", prepared_person_override_query)
        logger.info("Delete query for cohort people: %s", prepared_cohort_people_query)
        logger.info("Delete query for person: %s", prepared_person_query)


@dataclasses.dataclass
class DeletePersonsActivityInputs:
    """Inputs for the `delete_persons_activity`."""

    team_id: int
    person_ids: list[int] = dataclasses.field(default_factory=list)
    batch_number: int = 1
    batches: int = 1
    batch_size: int = 1000

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "batch_size": self.batch_size,
            "batch_number": self.batch_number,
            "batches": self.batches,
        }


@temporalio.activity.defn
async def delete_persons_activity(inputs: DeletePersonsActivityInputs) -> tuple[int, bool]:
    """Run queries to delete persons and associated entities."""
    async with Heartbeater():
        logger = LOGGER.bind()
        tag_queries(team_id=inputs.team_id)

        select_query = SELECT_QUERY.format(
            person_ids_filter=f"AND id IN {tuple(inputs.person_ids)}" if inputs.person_ids else ""
        )
        delete_query_person_distinct_ids = DELETE_QUERY_PERSON_DISTINCT_IDS.format(select_query=select_query)
        delete_query_person_override = DELETE_QUERY_PERSON_OVERRIDE.format(select_query=select_query)
        delete_query_cohort_people = DELETE_QUERY_COHORT_PEOPLE.format(select_query=select_query)
        delete_query_person = DELETE_QUERY_PERSON.format(select_query=select_query)

        conn = await psycopg.AsyncConnection.connect(settings.DATABASE_URL)
        async with conn:
            async with conn.cursor() as cursor:
                logger.info("Deleting batch %d of %d (%d rows)", inputs.batch_number, inputs.batches, inputs.batch_size)

                await cursor.execute(
                    delete_query_person_distinct_ids,
                    {"team_id": inputs.team_id, "limit": inputs.batch_size, "person_ids": inputs.person_ids},
                )
                logger.info("Deleted %d distinct_ids", cursor.rowcount)

                await cursor.execute(
                    delete_query_person_override,
                    {"team_id": inputs.team_id, "limit": inputs.batch_size, "person_ids": inputs.person_ids},
                )
                logger.info("Deleted %d person overrides", cursor.rowcount)

                await cursor.execute(
                    delete_query_cohort_people,
                    {"team_id": inputs.team_id, "limit": inputs.batch_size, "person_ids": inputs.person_ids},
                )
                logger.info(f"Deleted %d cohort people", cursor.rowcount)

                await cursor.execute(
                    delete_query_person,
                    {"team_id": inputs.team_id, "limit": inputs.batch_size, "person_ids": inputs.person_ids},
                )
                logger.info("Deleted %d persons", cursor.rowcount)

                should_continue = True
                if cursor.rowcount < inputs.batch_size:
                    await logger.ainfo("Workflow will exit early as we received less than %d rows", inputs.batch_size)
                    should_continue = False

                return cursor.rowcount, should_continue


@dataclasses.dataclass
class DeletePersonsWorkflowInputs:
    """Inputs for the `DeletePersonsWorkflow`."""

    team_id: int
    person_ids: list[int] = dataclasses.field(default_factory=list)
    batches: int = 1
    batch_size: int = 1000

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "batch_size": self.batch_size,
            "batches": self.batches,
        }


@temporalio.workflow.defn(name="delete-persons")
class DeletePersonsWorkflow(PostHogWorkflow):
    """Workflow to delete persons and associated entities from the PostHog database."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.paused = False
        self.confirmed = False

    @staticmethod
    def parse_inputs(inputs: list[str]) -> DeletePersonsWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return DeletePersonsWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: DeletePersonsWorkflowInputs):
        """Run all batches to delete persons.

        Before running batches, we will mogrify the queries and wait for a confirmation
        signal to be delivered.

        Before running every batch, we check to see if the `paused` signal has been
        received. If so, we halt execution until the signal is received again to unpause.
        """
        mogrify_delete_queries_activity_inputs = MogrifyDeleteQueriesActivityInputs(
            team_id=inputs.team_id,
            person_ids=inputs.person_ids,
            batch_size=inputs.batch_size,
        )

        await temporalio.workflow.execute_activity(
            mogrify_delete_queries_activity,
            mogrify_delete_queries_activity_inputs,
            heartbeat_timeout=dt.timedelta(seconds=30),
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
                non_retryable_error_types=[],
            ),
        )
        await temporalio.workflow.wait_condition(lambda: self.confirmed)

        for batch_number in range(0, inputs.batches):
            await temporalio.workflow.wait_condition(lambda: not self.paused)

            delete_persons_activity_inputs = DeletePersonsActivityInputs(
                team_id=inputs.team_id,
                person_ids=inputs.person_ids,
                batch_number=batch_number,
                batches=inputs.batches,
                batch_size=inputs.batch_size,
            )

            _, should_continue = await temporalio.workflow.execute_activity(
                delete_persons_activity,
                delete_persons_activity_inputs,
                heartbeat_timeout=dt.timedelta(seconds=30),
                start_to_close_timeout=dt.timedelta(hours=2),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=360),
                    maximum_attempts=0,
                    non_retryable_error_types=[],
                ),
            )

            if not should_continue:
                break

    @temporalio.workflow.signal
    async def confirm(self) -> None:
        """Signal handler for workflow confirmation to start."""
        async with self.lock:
            self.confirmed = True

    @temporalio.workflow.update
    async def pause(self) -> None:
        """Signal handler for workflow to pause or unpause."""
        async with self.lock:
            if self.paused is True:
                self.paused = False
            else:
                self.paused = True
