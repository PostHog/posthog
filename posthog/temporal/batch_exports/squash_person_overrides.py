import collections.abc
import contextlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Iterable, NamedTuple
from uuid import UUID

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client

EPOCH = datetime(1970, 1, 1, 0, 0, tzinfo=timezone.utc)


CREATE_DICTIONARY_QUERY = """
CREATE OR REPLACE DICTIONARY {database}.{dictionary_name} ON CLUSTER {cluster_name} (
    `team_id` Int64,
    `distinct_id` String,
    `person_id` UUID
)
PRIMARY KEY team_id, distinct_id
SOURCE(CLICKHOUSE(USER '{user}' PASSWORD '{password}' TABLE 'person_distinct_id_overrides' DB '{database}'))
LAYOUT(complex_key_hashed())
LIFETIME(0)
"""

SQUASH_EVENTS_QUERY = """
ALTER TABLE
    {database}.sharded_events
UPDATE
    person_id = dictGet('{database}.{dictionary_name}', 'person_id', (team_id, distinct_id))
IN PARTITION
    %(partition_id)s
WHERE
    dictHas('{database}.{dictionary_name}', (team_id, distinct_id))
    {in_team_ids}
"""

DROP_DICTIONARY_QUERY = """
DROP DICTIONARY {database}.{dictionary_name};
"""

CREATE_JOIN_TABLE_FOR_DELETES_QUERY = """
CREATE TABLE {database}.person_overrides_to_delete
ENGINE = Join(ANY, LEFT, team_id, distinct_id) AS
SELECT
    team_id, distinct_id, 1 AS exists
FROM
    {database}.sharded_events
WHERE
    dictHas('{database}.{dictionary_name}', (team_id, distinct_id))
    AND _partition_id IN %(partition_ids)s
"""

DROP_JOIN_TABLE_FOR_DELETES_QUERY = """
DROP TABLE IF EXISTS {database}.person_overrides_to_delete
"""

DELETE_SQUASHED_PERSON_OVERRIDES_QUERY = """
ALTER TABLE
    {database}.person_distinct_id_overrides
DELETE WHERE
    joinGet('{database}.person_overrides_to_delete', 'exists', team_id, distinct_id) = 1
"""


def parse_clickhouse_timestamp(s: str, tzinfo: timezone = timezone.utc) -> datetime:
    """Parse a timestamp from ClickHouse."""
    return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=tzinfo)


class PersonOverrideToDelete(NamedTuple):
    """A person override that should be deleted after squashing.

    Attributes:
        team_id: The id of the team that the person belongs to.
        old_person_id: The uuid of the person being overriden.
        override_person_id: The uuid of the person used as the override.
        latest_created_at: The latest override timestamp for overrides with this pair of ids. This is set by ClickHouse on INSERT.
        latest_version: The latest version for overrides with this pair of ids.
        oldest_event_at: The creation date of the oldest event for old_person_id.
    """

    team_id: int
    distinct_id: str
    override_person_id: UUID
    latest_version: int

    def _make_serializable(self) -> "SerializablePersonOverrideToDelete":
        return SerializablePersonOverrideToDelete._make(
            value.isoformat() if isinstance(value, datetime) else value for value in self
        )

    @classmethod
    def from_response_line(cls, response_line: str) -> "PersonOverrideToDelete":
        splitted = response_line.split("\t")
        return cls(
            team_id=int(splitted[0]),
            distinct_id=str(splitted[1]),
            override_person_id=UUID(splitted[2]),
            latest_version=int(splitted[4]),
        )


class SerializablePersonOverrideToDelete(NamedTuple):
    """A JSON serializable version of PersonOverrideToDelete.

    Only datetime types from PersonOverrideToDelete are not serializable by temporal's JSON
    encoder.
    """

    team_id: int
    distinct_id: str
    override_person_id: UUID
    latest_version: int


class PersonOverrideTuple(NamedTuple):
    distinct_id: str
    person_id: UUID


@dataclass
class QueryInputs:
    """Inputs for activities that run queries in the SquashPersonOverrides workflow.

    Attributes:
        clickhouse: Inputs required to connect to ClickHouse.
        postgres: Inputs required to connect to Postgres.
        partition_ids: When necessary, the partition ids this query should run on.
        person_overrides_to_delete: For delete queries, a list of PersonOverrideToDelete.
        database: The database where the query is supposed to run.
        user: Database username required to create a dictionary.
        password: Database password required to create a dictionary.
        dictionary_name: The name for a dictionary used in the join.
        wait_for_mutations: Whether to wait for mutations to finish or not.
        _latest_merged_at: A timestamp representing an upper bound for events to squash. Obtained
            as the latest timestamp of a person merge.
    """

    partition_ids: list[str] = field(default_factory=list)
    team_ids: list[int] = field(default_factory=list)
    person_overrides_to_delete: list[SerializablePersonOverrideToDelete] = field(default_factory=list)
    dictionary_name: str = "person_overrides_join_dict"
    dry_run: bool = True
    wait_for_mutations: bool = False

    def iter_person_overides_to_delete(self) -> Iterable[SerializablePersonOverrideToDelete]:
        """Iterate over SerializablePersonOverrideToDelete ensuring they are of that type.

        Looking at the types, this seems pointless, just iterate over person_overrides_to_delete!
        However, as Temporal passes inputs to and from activities, namedtuples will be cast to
        lists. This method thus exists to transform them back into namedtuples.
        """
        for person_override_to_delete in self.person_overrides_to_delete:
            yield SerializablePersonOverrideToDelete(*person_override_to_delete)


@activity.defn
async def prepare_person_overrides(inputs: QueryInputs) -> None:
    """Prepare the person_overrides table to be used in a squash.

    This activity executes an OPTIMIZE TABLE query to ensure we assign the latest overrides for each old_person_id.
    """
    from django.conf import settings

    detach_query = "DETACH TABLE {database}.kafka_person_distinct_id_overrides ON CLUSTER {cluster} SYNC"
    optimize_query = "OPTIMIZE TABLE {database}.person_distinct_id_overrides ON CLUSTER {cluster} FINAL"

    if inputs.dry_run is True:
        activity.logger.info("This is a DRY RUN so nothing will be detached or optimized.")
        activity.logger.debug("Detach query: %s", detach_query)
        activity.logger.debug("Optimize query: %s", optimize_query)
        return

    async with get_client(mutations_sync=2) as clickhouse_client:
        await clickhouse_client.execute_query(
            detach_query.format(database=settings.CLICKHOUSE_DATABASE, cluster=settings.CLICKHOUSE_CLUSTER)
        )
        activity.logger.info("Detached kafka_person_distinct_id_overrides")

        await clickhouse_client.execute_query(
            optimize_query.format(database=settings.CLICKHOUSE_DATABASE, cluster=settings.CLICKHOUSE_CLUSTER)
        )
    activity.logger.info("Optimized person_distinct_id_overrides")


@activity.defn
async def re_attach_person_overrides_kafka_table(inputs: QueryInputs) -> None:
    """Prepare the person_overrides table to be used in a squash.

    This activity executes an OPTIMIZE TABLE query to ensure we assign the latest overrides for each old_person_id.
    """
    from django.conf import settings

    attach_query = "ATTACH TABLE {database}.kafka_person_distinct_id_overrides ON CLUSTER {cluster}"

    if inputs.dry_run is True:
        activity.logger.info("This is a DRY RUN so nothing will be re-attached.")
        activity.logger.debug("Attach query: %s", attach_query)
        return

    async with get_client(mutations_sync=2) as clickhouse_client:
        await clickhouse_client.execute_query(
            attach_query.format(database=settings.CLICKHOUSE_DATABASE, cluster=settings.CLICKHOUSE_CLUSTER)
        )

    activity.logger.info("Re-attached kafka_person_distinct_id_overrides")


@activity.defn
async def prepare_dictionary(inputs: QueryInputs) -> None:
    """Prepare the dictionary to be used in the squash workflow.

    We also lock in the latest merged_at to ensure we do not process overrides that arrive after
    we have started the job.
    """
    from django.conf import settings

    async with get_client() as clickhouse_client:
        activity.logger.info("Creating squash dictionary: %s", inputs.dictionary_name)

        await clickhouse_client.execute_query(
            CREATE_DICTIONARY_QUERY.format(
                database=settings.CLICKHOUSE_DATABASE,
                dictionary_name=inputs.dictionary_name,
                user=settings.CLICKHOUSE_USER,
                password=settings.CLICKHOUSE_PASSWORD,
                cluster_name=settings.CLICKHOUSE_CLUSTER,
            )
        )


@activity.defn
async def drop_dictionary(inputs: QueryInputs) -> None:
    """DROP the dictionary used in the squash workflow."""
    from django.conf import settings

    activity.logger.info("Dropping dictionary %s", inputs.dictionary_name)

    async with get_client() as clickhouse_client:
        await clickhouse_client.execute_query(
            DROP_DICTIONARY_QUERY.format(
                database=settings.CLICKHOUSE_DATABASE,
                dictionary_name=inputs.dictionary_name,
            )
        )


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

    query = SQUASH_EVENTS_QUERY

    for partition_id in inputs.partition_ids:
        activity.logger.info("Executing squash query on partition %s", partition_id)

        parameters = {
            "partition_id": partition_id,
            "team_ids": inputs.team_ids,
        }

        if inputs.dry_run is True:
            activity.logger.info("This is a DRY RUN so nothing will be squashed.")
            activity.logger.info("Would have run query: %s with parameters %s", query, parameters)
            continue

        async with get_client(mutations_sync=1 if inputs.wait_for_mutations is True else 0) as clickhouse_client:
            query = query.format(
                database=settings.CLICKHOUSE_DATABASE,
                dictionary_name=inputs.dictionary_name,
                in_team_ids="AND team_id IN %(team_ids)s" if inputs.team_ids else "",
            )
            await clickhouse_client.execute_query(
                query,
                query_parameters=parameters,
            )


@activity.defn
async def delete_squashed_person_overrides_from_clickhouse(inputs: QueryInputs) -> None:
    """Execute the query to delete persons from ClickHouse that have been squashed."""
    from django.conf import settings

    activity.logger.info("Deleting squashed persons from ClickHouse")

    if inputs.dry_run is True:
        activity.logger.info("This is a DRY RUN so nothing will be deleted.")
        return

    async with get_client(mutations_sync=2 if inputs.wait_for_mutations is True else 0) as clickhouse_client:
        await clickhouse_client.execute_query(
            CREATE_JOIN_TABLE_FOR_DELETES_QUERY.format(
                database=settings.CLICKHOUSE_DATABASE, dictionary_name=inputs.dictionary_name
            ),
            query_parameters={
                "partition_ids": tuple(inputs.partition_ids),
            },
        )

        try:
            await clickhouse_client.execute_query(
                DELETE_SQUASHED_PERSON_OVERRIDES_QUERY.format(
                    database=settings.CLICKHOUSE_DATABASE, dictionary_name=inputs.dictionary_name
                ),
            )

        finally:
            await clickhouse_client.execute_query(
                DROP_JOIN_TABLE_FOR_DELETES_QUERY.format(database=settings.CLICKHOUSE_DATABASE),
            )


@contextlib.asynccontextmanager
async def person_overrides_dictionary(
    workflow, query_inputs: QueryInputs, retry_policy: RetryPolicy
) -> AsyncIterator[int]:
    """This context manager manages the person_overrides DICTIONARY used during a squash job.

    Managing the DICTIONARY involves setup activities:
    - Prepare the underlying person_overrides table optimizing the table to remove any duplicates.
    - Creating the DICTIONARY itself, returning latest_created_at.

    And clean-up activities:
    - Dropping the DICTIONARY.

    It's important that we account for possible cancellations with a try/finally block. However, if the
    squash workflow is terminated instead of cancelled, we may leave the underlying dictionary un-dropped.
    There is nothing we can do about this as termination leaves us no time to clean-up.
    """
    await workflow.execute_activity(
        prepare_person_overrides,
        query_inputs,
        start_to_close_timeout=timedelta(seconds=60),
        retry_policy=retry_policy,
    )

    await workflow.execute_activity(
        prepare_dictionary,
        query_inputs,
        start_to_close_timeout=timedelta(seconds=60),
        retry_policy=retry_policy,
    )

    try:
        yield

    finally:
        await workflow.execute_activity(
            drop_dictionary,
            query_inputs,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=retry_policy,
        )

        await workflow.execute_activity(
            re_attach_person_overrides_kafka_table,
            query_inputs,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=retry_policy,
        )


@dataclass
class SquashPersonOverridesInputs:
    """Inputs for the SquashPersonOverrides workflow.

    Attributes:
        clickhouse_database: The name of the ClickHouse database where to perform the squash.
        postgres_database: The name of the Postgres database where to delete overrides once done.
        dictionary_name: A name for the JOIN table created for the squash.
        team_ids: List of team ids to squash. If None, will squash all.
        partition_ids: Partitions to squash, preferred over last_n_months.
        last_n_months: Execute the squash on the partitions for the last_n_months.
        dry_run: If True, queries that mutate or delete data will not execute and instead will be logged.
    """

    team_ids: list[int] = field(default_factory=list)
    partition_ids: list[str] | None = None
    dictionary_name: str = "person_overrides_join_dict"
    last_n_months: int = 1
    dry_run: bool = True
    wait_for_mutations: bool = False

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
        workflow.logger.debug("%s", json.dumps(asdict(inputs)))

        retry_policy = RetryPolicy(maximum_attempts=3)
        query_inputs = QueryInputs(
            dictionary_name=inputs.dictionary_name,
            team_ids=inputs.team_ids,
            dry_run=inputs.dry_run,
            wait_for_mutations=inputs.wait_for_mutations,
        )

        async with person_overrides_dictionary(
            workflow,
            query_inputs,
            # Let's be kinder to ClickHouse when running ON CLUSTER queries.
            # We use a higher initial_interval for retries so that we let ClickHouse finish up.
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=20)),
        ):
            query_inputs.partition_ids = list(inputs.iter_partition_ids())

            await workflow.execute_activity(
                squash_events_partition,
                query_inputs,
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=retry_policy,
            )

            workflow.logger.info("Squash finished for all requested partitions, running clean up activities")

            await workflow.execute_activity(
                delete_squashed_person_overrides_from_clickhouse,
                query_inputs,
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=retry_policy,
            )

        workflow.logger.info("Done 🎉")
