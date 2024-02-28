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


CREATE_DICTIONARY_QUERY = """
CREATE OR REPLACE DICTIONARY {database}.{dictionary_name} ON CLUSTER {cluster_name} (
    `team_id` Int64,
    `distinct_id` String,
    `person_id` UUID
)
PRIMARY KEY team_id, distinct_id
SOURCE(CLICKHOUSE(
    USER '{user}'
    PASSWORD '{password}'
    DB '{database}'
    QUERY 'SELECT team_id, distinct_id, argMax(person_id, version) AS person_id FROM {database}.person_distinct_id_overrides GROUP BY team_id, distinct_id'
))
LAYOUT(complex_key_hashed())
LIFETIME(MIN 0 MAX 0)
"""

RELOAD_DICTIONARY_QUERY = """
SYSTEM RELOAD DICTIONARY {database}.{dictionary_name}
"""

SQUASH_EVENTS_QUERY = """
ALTER TABLE
    {database}.sharded_events
ON CLUSTER
    {cluster}
UPDATE
    person_id = dictGet('{database}.{dictionary_name}', 'person_id', (team_id, distinct_id))
IN PARTITION
    %(partition_id)s
WHERE
    dictHas('{database}.{dictionary_name}', (team_id, distinct_id))
    {in_team_ids}
"""

SQUASH_MUTATIONS_IN_PROGRESS_QUERY = """
SELECT mutation_id, is_done
FROM clusterAllReplicas('{cluster}', 'system', mutations)
WHERE table = 'sharded_events'
AND database = '{database}'
AND command LIKE
    'UPDATE person_id = dictGet(''{database}.{dictionary_name}'', ''person_id'', (team_id, distinct_id)) IN PARTITION ''{partition_id}''%'
"""

KILL_SQUASH_MUTATION_IN_PROGRESS_QUERY = """
KILL MUTATION ON CLUSTER {cluster}
WHERE is_done = 0
AND table = 'sharded_events'
AND database = '{database}'
AND command LIKE
    'UPDATE person_id = dictGet(''{database}.{dictionary_name}'', ''person_id'', (team_id, distinct_id)) IN PARTITION '''{partition_id}''%'
"""

DROP_DICTIONARY_QUERY = """
DROP DICTIONARY {database}.{dictionary_name};
"""

CREATE_JOIN_TABLE_FOR_DELETES_QUERY = """
CREATE TABLE {database}.person_overrides_to_delete
ENGINE = Join(ANY, LEFT, team_id, distinct_id) AS
SELECT
    team_id, distinct_id, groupUniqArray(_partition_id) AS partitions
FROM
    {database}.sharded_events
WHERE
    dictHas('{database}.{dictionary_name}', (team_id, distinct_id))
GROUP BY
    team_id, distinct_id
"""

DROP_JOIN_TABLE_FOR_DELETES_QUERY = """
DROP TABLE IF EXISTS {database}.person_overrides_to_delete
"""

DELETE_SQUASHED_PERSON_OVERRIDES_QUERY = """
ALTER TABLE
    {database}.person_distinct_id_overrides
DELETE WHERE
    hasAll(joinGet('{database}.person_overrides_to_delete', 'partitions', team_id, distinct_id), %(partition_ids)s)
    AND NOW() - _timestamp > %(grace_period)s
"""


def parse_clickhouse_timestamp(s: str, tzinfo: timezone = timezone.utc) -> datetime:
    """Parse a timestamp from ClickHouse."""
    return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=tzinfo)


@dataclass
class QueryInputs:
    """Inputs for activities that run queries in the SquashPersonOverrides workflow.

    Attributes:
        partition_ids: Run a query only on a subset of partitions. Not supported by all queries.
        team_ids: Run a query only on a subset of teams. Not supported by all queries.
        dictionary_name: The name for a dictionary used in the join.
        delete_grace_period_seconds: Number of seconds until an override can be deleted. This grace
            period works on top of checking if the override was applied to all partitions. Defaults
            to 24h.
        dry_run: Do not run the queries when True.
    """

    partition_ids: list[str] = field(default_factory=list)
    team_ids: list[int] = field(default_factory=list)
    dictionary_name: str = "person_overrides_join_dict"
    delete_grace_period_seconds: int = 24 * 3600
    dry_run: bool = True


@activity.defn
async def optimize_person_distinct_id_overrides(inputs: QueryInputs) -> None:
    """Prepare the person_overrides table to be used in a squash.

    This activity executes an OPTIMIZE TABLE query to ensure we assign the latest overrides for each old_person_id.
    """
    from django.conf import settings

    optimize_query = "OPTIMIZE TABLE {database}.person_distinct_id_overrides ON CLUSTER {cluster} FINAL"

    if inputs.dry_run is True:
        activity.logger.info("This is a DRY RUN so nothing will be detached or optimized.")
        activity.logger.debug("Optimize query: %s", optimize_query)
        return

    async with heartbeat_every():
        async with get_client(mutations_sync=2) as clickhouse_client:
            await clickhouse_client.execute_query(
                optimize_query.format(database=settings.CLICKHOUSE_DATABASE, cluster=settings.CLICKHOUSE_CLUSTER)
            )
    activity.logger.info("Optimized person_distinct_id_overrides")


@activity.defn
async def prepare_dictionary(inputs: QueryInputs) -> None:
    """Prepare the DICTIONARY to be used in the squash workflow."""
    from django.conf import settings

    async with heartbeat_every():
        async with get_client() as clickhouse_client:
            await clickhouse_client.execute_query(
                CREATE_DICTIONARY_QUERY.format(
                    database=settings.CLICKHOUSE_DATABASE,
                    dictionary_name=inputs.dictionary_name,
                    user=settings.CLICKHOUSE_USER,
                    password=settings.CLICKHOUSE_PASSWORD,
                    cluster_name=settings.CLICKHOUSE_CLUSTER,
                )
            )
            # ClickHouse may delay populating the dictionary until we read from it.
            # We force a reload here to ensure the values are populated. This way,
            # they remain static from this point onwards as the dictionary's lifetime
            # is 0 (no updates).
            await clickhouse_client.execute_query(
                RELOAD_DICTIONARY_QUERY.format(
                    database=settings.CLICKHOUSE_DATABASE,
                    dictionary_name=inputs.dictionary_name,
                )
            )

    activity.logger.info("Created dictionary %s", inputs.dictionary_name)


@activity.defn
async def drop_dictionary(inputs: QueryInputs) -> None:
    """DROP the dictionary used in the squash workflow."""
    from django.conf import settings

    async with get_client() as clickhouse_client:
        await clickhouse_client.execute_query(
            DROP_DICTIONARY_QUERY.format(
                database=settings.CLICKHOUSE_DATABASE,
                dictionary_name=inputs.dictionary_name,
            )
        )

    activity.logger.info("Dropped dictionary %s", inputs.dictionary_name)


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
async def squash_events_partition(inputs: QueryInputs) -> None:
    """Execute the squash query for a given partition_id and persons to_override.

    As ClickHouse doesn't support an UPDATE ... FROM statement ala PostgreSQL, we must
    do this in 4 basic steps:

    1. Stop ingesting data into person_overrides.
    2. Build a DICTIONARY from person_overrides.
    3. Perform ALTER TABLE UPDATE using dictGet to query the DICTIONARY.
    4. Clean up the DICTIONARY once done.
    """
    from django.conf import settings

    finished_partition_ids: list[str] = []

    if inputs.dry_run is True:
        activity.logger.info("This is a DRY RUN so nothing will be squashed.")
        return

    async with get_client() as clickhouse_client:
        for partition_id in inputs.partition_ids:
            activity.logger.info("Updating events with person overrides in partition %s", partition_id)

            query = SQUASH_EVENTS_QUERY.format(
                database=settings.CLICKHOUSE_DATABASE,
                cluster=settings.CLICKHOUSE_CLUSTER,
                dictionary_name=inputs.dictionary_name,
                partition_id=partition_id,
                in_team_ids="AND team_id IN %(team_ids)s" if inputs.team_ids else "",
            )

            parameters = {
                "partition_id": partition_id,
                "team_ids": inputs.team_ids,
            }

            # Best cancellation scenario: It fires off before we begin a new mutation and there is nothing to cancel.
            activity.heartbeat(finished_partition_ids)

            await clickhouse_client.execute_query(
                query,
                query_parameters=parameters,
            )

            activity.logger.info("Person overrides update submitted in partition %", partition_id)

            try:
                while True:
                    activity.heartbeat(finished_partition_ids)

                    response = await clickhouse_client.read_query(
                        SQUASH_MUTATIONS_IN_PROGRESS_QUERY.format(
                            database=settings.CLICKHOUSE_DATABASE,
                            cluster=settings.CLICKHOUSE_CLUSTER,
                            dictionary_name=inputs.dictionary_name,
                            partition_id=partition_id,
                        ),
                    )
                    rows = []
                    for line in response.decode("utf-8").splitlines():
                        mutation_id, is_done = line.strip().split("\t")
                        rows.append((mutation_id, int(is_done)))

                    total_mutations = len(rows)
                    mutations_in_progress = sum(row[1] == 0 for row in rows)

                    if mutations_in_progress == 0 and total_mutations > 0:
                        break

                    activity.logger.info("Waiting for mutation in partition %", partition_id)

                    await asyncio.sleep(5)

            except asyncio.CancelledError:
                activity.logger.warning(
                    "Squash activity has been cancelled, attempting to kill in progress mutation for partition %",
                    partition_id,
                )

                await clickhouse_client.execute_query(
                    KILL_SQUASH_MUTATION_IN_PROGRESS_QUERY.format(
                        database=settings.CLICKHOUSE_DATABASE,
                        cluster=settings.CLICKHOUSE_CLUSTER,
                        dictionary_name=inputs.dictionary_name,
                        partition_id=partition_id,
                    ),
                )
                raise

            else:
                finished_partition_ids.append(partition_id)

                activity.logger.info("Person overrides update finished in partition %", partition_id)

        activity.logger.info("All partitions have been updated with person overrides")


@activity.defn
async def delete_squashed_person_overrides_from_clickhouse(inputs: QueryInputs) -> None:
    """Execute the query to delete person overrides from ClickHouse that have been squashed."""
    from django.conf import settings

    activity.logger.info("Starting to delete squashed persons from ClickHouse")

    if inputs.dry_run is True:
        activity.logger.info("This is a DRY RUN so nothing will be deleted.")
        return

    async with heartbeat_every():
        async with get_client(mutations_sync=2) as clickhouse_client:
            await clickhouse_client.execute_query(
                CREATE_JOIN_TABLE_FOR_DELETES_QUERY.format(
                    database=settings.CLICKHOUSE_DATABASE, dictionary_name=inputs.dictionary_name
                ),
            )

            try:
                await clickhouse_client.execute_query(
                    DELETE_SQUASHED_PERSON_OVERRIDES_QUERY.format(
                        database=settings.CLICKHOUSE_DATABASE, dictionary_name=inputs.dictionary_name
                    ),
                    query_parameters={
                        "partition_ids": inputs.partition_ids,
                        "grace_period": inputs.delete_grace_period_seconds,
                    },
                )

            finally:
                await clickhouse_client.execute_query(
                    DROP_JOIN_TABLE_FOR_DELETES_QUERY.format(database=settings.CLICKHOUSE_DATABASE),
                )

    activity.logger.info("Deleted squashed persons from ClickHouse")


@contextlib.asynccontextmanager
async def person_overrides_dictionary(workflow, query_inputs: QueryInputs) -> collections.abc.AsyncIterator[None]:
    """This context manager manages a dictionary used during a squash workflow.

    Managing the dictionary involves setup activities necessary to ensure accurate values land in the
    dictionary:
    - Optimizing the table to remove any duplicates.

    At exciting the context manager, we run clean-up activities:
    - Dropping the dictionary.

    It's important that we account for possible cancellations with a try/finally block. However, if the
    squash workflow is terminated instead of cancelled, we may not have a chance to run the aforementioned
    clean-up activies. This could leave the dictionary lingering around. There is nothing we can do
    about this as termination leaves us no time to clean-up.

    TODO: Get rid of this and instead use a migration to add a permanent dictionary.
    """
    await workflow.execute_activity(
        optimize_person_distinct_id_overrides,
        query_inputs,
        start_to_close_timeout=timedelta(minutes=30),
        retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=20)),
        heartbeat_timeout=timedelta(minutes=1),
    )

    await workflow.execute_activity(
        prepare_dictionary,
        query_inputs,
        start_to_close_timeout=timedelta(minutes=30),
        retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=20)),
        heartbeat_timeout=timedelta(minutes=1),
    )

    try:
        yield None

    finally:
        await workflow.execute_activity(
            drop_dictionary,
            query_inputs,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=10, initial_interval=timedelta(seconds=60)),
            heartbeat_timeout=timedelta(seconds=10),
        )


@dataclass
class SquashPersonOverridesInputs:
    """Inputs for the SquashPersonOverrides workflow.

    Attributes:
        team_ids: List of team ids to squash. If None, will squash all.
        partition_ids: Partitions to squash, preferred over last_n_months.
        dictionary_name: A name for the JOIN table created for the squash.
        last_n_months: Execute the squash on the partitions for the last_n_months.
        delete_grace_period_seconds: Number of seconds until an override can be deleted. This grace
            period works on top of checking if the override was applied to all partitions. Defaults
            to 24h.
        dry_run: If True, queries that mutate or delete data will not execute and instead will be logged.
    """

    team_ids: list[int] = field(default_factory=list)
    partition_ids: list[str] | None = None
    dictionary_name: str = "person_overrides_join_dict"
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
    person ID. The ``posthog_flatpersonoverride`` table is the primary
    representation of this data in Postgres. The ``person_overrides`` table in
    ClickHouse contains a replica of the data stored in Postgres, and can be
    joined onto the events table to get the most up-to-date person for an event.

    This process must be done regularly to control the size of the person
    overrides tables -- both to reduce the amount of storage required for these
    tables, as well as ensuring that the join mentioned previously does not
    become prohibitively large to evaluate.
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

        query_inputs = QueryInputs(
            dictionary_name=inputs.dictionary_name,
            team_ids=inputs.team_ids,
            dry_run=inputs.dry_run,
            delete_grace_period_seconds=inputs.delete_grace_period_seconds,
        )

        async with person_overrides_dictionary(
            workflow,
            query_inputs,
        ):
            query_inputs.partition_ids = list(inputs.iter_partition_ids())

            await workflow.execute_activity(
                squash_events_partition,
                query_inputs,
                start_to_close_timeout=timedelta(hours=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
                heartbeat_timeout=timedelta(minutes=1),
            )

            workflow.logger.info("Squash finished for all requested partitions, running clean up activities")

            await workflow.execute_activity(
                delete_squashed_person_overrides_from_clickhouse,
                query_inputs,
                start_to_close_timeout=timedelta(hours=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
                heartbeat_timeout=timedelta(minutes=1),
            )

        workflow.logger.info("Done 🎉")
