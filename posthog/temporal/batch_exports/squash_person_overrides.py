import asyncio
import collections.abc
import contextlib
import dataclasses
import json
import typing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.utils import EmptyHeartbeatError, HeartbeatDetails

EPOCH = datetime(1970, 1, 1, 0, 0, tzinfo=timezone.utc)

RELOAD_DICTIONARY_QUERY = """
SYSTEM RELOAD DICTIONARY {database}.person_distinct_id_overrides_dict ON CLUSTER {cluster}
"""

SQUASH_EVENTS_QUERY = """
ALTER TABLE
    {database}.sharded_events
ON CLUSTER
    {cluster}
UPDATE
    person_id = dictGet('{database}.person_distinct_id_overrides_dict', 'person_id', (team_id, distinct_id))
IN PARTITION
    %(partition_id)s
WHERE
    dictHas('{database}.person_distinct_id_overrides_dict', (team_id, distinct_id))
    {in_team_ids}
SETTINGS
    max_execution_time = 0
"""

MUTATIONS_IN_PROGRESS_QUERY = """
SELECT mutation_id, is_done
FROM clusterAllReplicas('{cluster}', 'system', mutations)
WHERE table = '{table}'
AND database = '{database}'
AND command LIKE %(query)s
"""

KILL_MUTATION_IN_PROGRESS_QUERY = """
KILL MUTATION ON CLUSTER {cluster}
WHERE is_done = 0
WHERE table = '{table}'
AND database = '{database}'
AND command LIKE %(query)s
"""

CREATE_JOIN_TABLE_FOR_DELETES_QUERY = """
CREATE TABLE {database}.person_overrides_to_delete ON CLUSTER {cluster}
ENGINE = Join(ANY, LEFT, team_id, distinct_id) AS
SELECT
    team_id, distinct_id, groupUniqArray(_partition_id) AS partitions
FROM
    {database}.sharded_events
WHERE
    dictHas('{database}.person_distinct_id_overrides_dict', (team_id, distinct_id))
GROUP BY
    team_id, distinct_id
"""

DROP_JOIN_TABLE_FOR_DELETES_QUERY = """
DROP TABLE IF EXISTS {database}.person_overrides_to_delete
"""

DELETE_SQUASHED_PERSON_OVERRIDES_QUERY = """
ALTER TABLE
    {database}.person_distinct_id_overrides
ON CLUSTER
    {cluster}
DELETE WHERE
    hasAll(joinGet('{database}.person_overrides_to_delete', 'partitions', team_id, distinct_id), %(partition_ids)s)
    AND ((now() - _timestamp) > %(grace_period)s)
SETTINGS
    max_execution_time=0
"""


def parse_clickhouse_timestamp(s: str, tzinfo: timezone = timezone.utc) -> datetime:
    """Parse a timestamp from ClickHouse."""
    return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=tzinfo)


@dataclass
class DeletePersonOverridesInputs:
    """Inputs for squashed person overrides deletion activity.

    Attributes:
        partition_ids: Partitions that must have been squashed for an override to be delete-able.
        delete_grace_period_seconds: Number of seconds until an override can be deleted. This grace
            period works on top of checking if the override was applied to all partitions. Defaults
            to 24h.
        dry_run: Do not run the queries when True.
    """

    dry_run: bool = True
    partition_ids: list[str] = field(default_factory=list)
    delete_grace_period_seconds: int = 24 * 3600


@dataclass
class SquashEventsPartitionInputs:
    """Inputs for the main squash events activity.

    Attributes:
        partition_id: Squash only given partition. The Workflow iterates over all provided
            partition_ids.
        team_ids: Run squash only on a subset of teams.
        delete_grace_period_seconds: Number of seconds until an override can be deleted. This grace
            period works on top of checking if the override was applied to all partitions. Defaults
            to 24h.
        dry_run: Do not run the queries when True.
    """

    partition_id: str | None = None
    team_ids: list[int] = field(default_factory=list)
    dry_run: bool = True


@dataclass
class WaitForMutationInputs:
    """Inputs the wait_for_mutation activity.

    Attributes:
        table: The table name which we are waiting to be mutated.
        query: The mutation query.
        dry_run: Do not run the queries when True.
    """

    table: str
    query: str
    dry_run: bool = True


@activity.defn
async def optimize_person_distinct_id_overrides(dry_run: bool) -> None:
    """Prepare the person_distinct_id_overrides table to be used in a squash.

    This activity executes an OPTIMIZE TABLE query to ensure we assign the latest overrides for each distinct_id.
    """
    from django.conf import settings

    optimize_query = "OPTIMIZE TABLE {database}.person_distinct_id_overrides ON CLUSTER {cluster} FINAL"

    if dry_run is True:
        activity.logger.info("This is a DRY RUN so nothing will be optimized.")
        activity.logger.debug("Optimize query: %s", optimize_query)
        return

    async with heartbeat_every():
        async with get_client(mutations_sync=2) as clickhouse_client:
            await clickhouse_client.execute_query(
                optimize_query.format(database=settings.CLICKHOUSE_DATABASE, cluster=settings.CLICKHOUSE_CLUSTER)
            )
    activity.logger.info("Optimized person_distinct_id_overrides")


@activity.defn
async def prepare_dictionary(dry_run: bool) -> None:
    """Prepare the DICTIONARY to be used in the squash workflow."""
    from django.conf import settings

    if dry_run is True:
        activity.logger.info("This is a DRY RUN so no dictionary will be created.")
        return

    async with heartbeat_every():
        async with get_client() as clickhouse_client:
            # ClickHouse may delay populating the dictionary until we read from it.
            # We force a reload here to ensure the values are populated. This way,
            # the squash mutation that follows will run with the latest overrides.
            await clickhouse_client.execute_query(
                RELOAD_DICTIONARY_QUERY.format(
                    database=settings.CLICKHOUSE_DATABASE,
                    cluster=settings.CLICKHOUSE_CLUSTER,
                )
            )
    activity.logger.info("Reloaded dictionary")


@dataclasses.dataclass
class SquashHeartbeatDetails(HeartbeatDetails):
    """Squash heartbeat details.

    Attributes:
        partition_ids: The endpoint we are importing data from.
    """

    partition_ids: list[str]

    @classmethod
    def from_activity(cls, activity):
        """Attempt to initialize SquashHeartbeatDetails from an activity's info."""
        details = activity.info().heartbeat_details

        if len(details) == 0:
            raise EmptyHeartbeatError()

        return cls(partition_ids=details[0], _remaining=details[1:])


def no_details() -> tuple:
    """No heartbeat details."""
    return ()


@contextlib.asynccontextmanager
async def heartbeat_every(
    factor: int = 2,
    details_callable: collections.abc.Callable[[], tuple[typing.Any]] = no_details,
) -> collections.abc.AsyncIterator[None]:
    """Heartbeat every Activity heartbeat timeout / factor seconds while in context."""
    heartbeat_timeout = activity.info().heartbeat_timeout
    heartbeat_task = None

    async def heartbeat_forever(delay: float) -> None:
        """Heartbeat forever every delay seconds."""
        while True:
            await asyncio.sleep(delay)
            activity.heartbeat(*details_callable())

    if heartbeat_timeout:
        heartbeat_task = asyncio.create_task(heartbeat_forever(heartbeat_timeout.total_seconds() / factor))

    try:
        yield
    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
            await asyncio.wait([heartbeat_task])


@activity.defn
async def squash_events_partition(inputs: SquashEventsPartitionInputs) -> str:
    """Execute the squash query for a given partition_id and persons to_override.

    This activity will submit a mutation to be executed to apply all overrides available
    in the person_distinct_id_overrides_dict DICTIONARY. A wait_for_mutation activity should
    run after this one with the returned query to ensure the mutation is waited for.
    """
    from django.conf import settings

    async with get_client() as clickhouse_client:
        activity.logger.info("Updating events with person overrides in partition %s", inputs.partition_id)

        query = SQUASH_EVENTS_QUERY.format(
            database=settings.CLICKHOUSE_DATABASE,
            cluster=settings.CLICKHOUSE_CLUSTER,
            partition_id=inputs.partition_id,
            in_team_ids="AND (team_id IN %(team_ids)s)" if inputs.team_ids else "",
        )

        parameters = {
            "partition_id": inputs.partition_id,
            "team_ids": inputs.team_ids,
        }
        prepared_query = clickhouse_client.prepare_query(query, parameters)

        if inputs.dry_run is True:
            activity.logger.info("This is a DRY RUN so nothing will be squashed.")
            activity.logger.debug(prepared_query)

            return prepared_query

        # Best cancellation scenario: It fires off before we begin a new mutation and there is nothing to cancel.
        activity.heartbeat()

        await clickhouse_client.execute_query(prepared_query)

    activity.logger.info("Person overrides update submitted in partition %", inputs.partition_id)

    return prepared_query


def parse_mutation_counts(response: bytes) -> tuple[int, int]:
    """Parse the count of total mutations and mutations in progress."""
    rows = []

    for line in response.decode("utf-8").splitlines():
        mutation_id, is_done = line.strip().split("\t")
        rows.append((mutation_id, int(is_done)))

    total_mutations = len(rows)
    mutations_in_progress = sum(row[1] == 0 for row in rows)

    return (mutations_in_progress, total_mutations)


@activity.defn
async def wait_for_mutation(inputs: WaitForMutationInputs) -> None:
    """Wait for a mutation to finish.

    The mutation we wait for is given by WaitForMutationInputs.query and
    WaitForMutationInputs.table. The former should be the 'ALTER TABLE' query used to
    start the mutation.

    WARNING: The 'ALTER TABLE' query should be formatted by ClickHouse as it's used as
    an exact filter predicate. ClickHouse sometimes adds additional parantheses, or changes
    the casing of functions, which can make the filter miss.

    We wait for the mutation to be done in the whole cluster.
    """
    from django.conf import settings

    if inputs.dry_run is True:
        activity.logger.info("This is a DRY RUN so nothing will be waited for.")
        return

    # Mutations start with 'ALTER TABLE {table identifier} ON CLUSTER {cluster}'.
    # The mutation command comes right after, and its one of 'UPDATE', 'DELETE WHERE', etc..., statements.
    # So, we split and look for index 6 to find the start of the command:
    # ["ALTER", "TABLE", "{table identifier}", "ON", "CLUSTER", "{cluster}", "{command}"].
    try:
        query_command = " ".join(inputs.query.split()[6:])
        # Also we get rid of any SETTINGS clause as these are not passed along as a command.
        query_command = query_command.split("SETTINGS")[0].strip()
    except IndexError:
        raise ValueError("Provided query does not appear to be a ALTER TABLE mutation")

    async with get_client() as clickhouse_client:
        try:
            async with heartbeat_every():
                while True:
                    response = await clickhouse_client.read_query(
                        MUTATIONS_IN_PROGRESS_QUERY.format(
                            database=settings.CLICKHOUSE_DATABASE,
                            cluster=settings.CLICKHOUSE_CLUSTER,
                            table=inputs.table,
                        ),
                        query_parameters={"query": query_command},
                    )

                    mutations_in_progress, total_mutations = parse_mutation_counts(response)

                    if mutations_in_progress == 0 and total_mutations > 0:
                        break

                    activity.logger.info("Waiting for mutation in table %s", {inputs.table})

                    await asyncio.sleep(5)

        except asyncio.CancelledError:
            activity.logger.warning(
                "Activity has been cancelled, attempting to kill in progress mutation for table %s",
                inputs.table,
            )

            await clickhouse_client.execute_query(
                KILL_MUTATION_IN_PROGRESS_QUERY.format(
                    database=settings.CLICKHOUSE_DATABASE,
                    cluster=settings.CLICKHOUSE_CLUSTER,
                    table=inputs.table,
                ),
                query_parameters={"query": query_command},
            )
            raise

        else:
            activity.logger.info("Mutation finished in table %s", inputs.table)


@activity.defn
async def delete_squashed_person_overrides_from_clickhouse(inputs: DeletePersonOverridesInputs) -> str:
    """Execute the query to delete person overrides from ClickHouse that have been squashed."""
    from django.conf import settings

    activity.logger.info("Starting to delete squashed person overrides from ClickHouse")

    async with heartbeat_every():
        async with get_client() as clickhouse_client:
            delete_query = DELETE_SQUASHED_PERSON_OVERRIDES_QUERY.format(
                database=settings.CLICKHOUSE_DATABASE,
                cluster=settings.CLICKHOUSE_CLUSTER,
            )
            query_parameters = {
                "partition_ids": inputs.partition_ids,
                "grace_period": inputs.delete_grace_period_seconds,
            }

            prepared_delete_query = clickhouse_client.prepare_query(delete_query, query_parameters)

            if inputs.dry_run is True:
                activity.logger.info("This is a DRY RUN so nothing will be deleted.")
                return prepared_delete_query

            await clickhouse_client.execute_query(
                CREATE_JOIN_TABLE_FOR_DELETES_QUERY.format(
                    database=settings.CLICKHOUSE_DATABASE,
                    cluster=settings.CLICKHOUSE_CLUSTER,
                ),
            )

    async with heartbeat_every():
        async with get_client() as clickhouse_client:
            try:
                await clickhouse_client.execute_query(prepared_delete_query)

            finally:
                await clickhouse_client.execute_query(
                    DROP_JOIN_TABLE_FOR_DELETES_QUERY.format(
                        database=settings.CLICKHOUSE_DATABASE,
                        cluster=settings.CLICKHOUSE_CLUSTER,
                    ),
                )

    activity.logger.info("Deleted squashed person overrides from ClickHouse")
    return prepared_delete_query


@dataclass
class SquashPersonOverridesInputs:
    """Inputs for the SquashPersonOverrides workflow.

    Attributes:
        team_ids: List of team ids to squash. If None, will squash all.
        partition_ids: Partitions to squash, preferred over last_n_months.
        last_n_months: Execute the squash on the partitions for the last_n_months.
        delete_grace_period_seconds: Number of seconds until an override can be deleted. This grace
            period works on top of checking if the override was applied to all partitions. Defaults
            to 24h.
        dry_run: If True, queries that mutate or delete data will not execute and instead will be logged.
    """

    team_ids: list[int] = field(default_factory=list)
    partition_ids: list[str] | None = None
    last_n_months: int = 1
    delete_grace_period_seconds: int = 24 * 3600
    dry_run: bool = True

    def iter_partition_ids(self) -> collections.abc.Iterator[str]:
        """Iterate over configured partition ids.

        If partition_ids is set, then we will just yield from that.
        Otherwise, we compute the partition keys for the last_n_months.
        """
        if self.partition_ids:
            yield from self.partition_ids
            return

        for month in self.iter_last_n_months():
            yield month.strftime("%Y%m")

    def iter_last_n_months(self) -> collections.abc.Iterator[datetime]:
        """Iterate over the last N months.

        Returns the first day of the last N months. The current month
        counts as the first month.
        """
        current_month = datetime.now()

        for _ in range(self.last_n_months):
            current_month = current_month.replace(day=1)

            yield current_month

            current_month = current_month - timedelta(days=1)


@workflow.defn(name="squash-person-overrides")
class SquashPersonOverridesWorkflow(PostHogWorkflow):
    """Workflow to squash outstanding person overrides into events.

    Squashing refers to the process of updating the person ID of existing
    ClickHouse event records on disk to reflect their most up-to-date person ID.

    The persons associated with existing events can change as a result of
    actions such as person merges. To account for this, we keep a record of what
    new person ID should be used in place of (or "override") a previously used
    person ID.  The 'person_distinct_id_overrides' table in ClickHouse contains
    the overrides as they are read from Postgres, and can be joined onto the
    events table to get the most up-to-date person for an event.

    This process must be done regularly to control the size of the
    person_distinct_id_overrides table: both to reduce the amount of storage
    required for these tables, as well as ensuring that the join mentioned
    previously does not become prohibitively large to evaluate.

    As ClickHouse doesn't support an UPDATE ... FROM statement ala PostgreSQL,
    applying the overrides on the events table (i.e. "squashing") is a 4-step
    process:

    1. Build a DICTIONARY from person_distinct_id_overrides.
    2. For each partition issue an ALTER TABLE UPDATE. This query uses dictGet
        to efficiently find the override for each (team_id, distinct_id) pair
        in the dictionary we built in 1.
    3. Delete from person_distinct_id_overrides any overrides that were squashed
        and are past the grace period. We construct an auxiliary JOIN table to
        identify the persons that can be deleted.
    4. Clean up the DICTIONARY and auxiliary JOIN table once done.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SquashPersonOverridesInputs:
        """Parse inputs from the management command CLI.

        We assume only one JSON serialized input and go from there.
        """
        if not inputs:
            return SquashPersonOverridesInputs()

        loaded = json.loads(inputs[0])
        return SquashPersonOverridesInputs(**loaded)

    @workflow.run
    async def run(self, inputs: SquashPersonOverridesInputs):
        """Workflow implementation to squash person overrides into events table."""
        workflow.logger.info("Starting squash workflow")

        await workflow.execute_activity(
            optimize_person_distinct_id_overrides,
            inputs.dry_run,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=20)),
            heartbeat_timeout=timedelta(minutes=1),
        )

        await workflow.execute_activity(
            prepare_dictionary,
            inputs.dry_run,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=20)),
            heartbeat_timeout=timedelta(minutes=1),
        )

        for partition_id in inputs.iter_partition_ids():
            squash_events_partition_inputs = SquashEventsPartitionInputs(
                dry_run=inputs.dry_run,
                team_ids=inputs.team_ids,
                partition_id=partition_id,
            )
            squash_events_partition_inputs.partition_id = partition_id
            mutation_query = await workflow.execute_activity(
                squash_events_partition,
                squash_events_partition_inputs,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=1),
                heartbeat_timeout=timedelta(seconds=10),
            )

            wait_for_mutation_inputs = WaitForMutationInputs(
                dry_run=inputs.dry_run,
                query=mutation_query,
                table="sharded_events",
            )
            await workflow.execute_activity(
                wait_for_mutation,
                wait_for_mutation_inputs,
                start_to_close_timeout=timedelta(hours=4),
                retry_policy=RetryPolicy(maximum_attempts=6, initial_interval=timedelta(seconds=20)),
                heartbeat_timeout=timedelta(minutes=2),
            )

        workflow.logger.info("Squash finished for all requested partitions, now deleting person overrides")

        delete_person_overrides_inputs = DeletePersonOverridesInputs(
            dry_run=inputs.dry_run,
            delete_grace_period_seconds=inputs.delete_grace_period_seconds,
            partition_ids=list(inputs.iter_partition_ids()),
        )
        mutation_query = await workflow.execute_activity(
            delete_squashed_person_overrides_from_clickhouse,
            delete_person_overrides_inputs,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
            heartbeat_timeout=timedelta(seconds=10),
        )

        wait_for_mutation_inputs = WaitForMutationInputs(
            dry_run=inputs.dry_run,
            query=mutation_query,
            table="person_distinct_id_overrides",
        )
        await workflow.execute_activity(
            wait_for_mutation,
            wait_for_mutation_inputs,
            start_to_close_timeout=timedelta(hours=4),
            retry_policy=RetryPolicy(maximum_attempts=6, initial_interval=timedelta(seconds=20)),
            heartbeat_timeout=timedelta(minutes=2),
        )

        workflow.logger.info("Done 🎉")
