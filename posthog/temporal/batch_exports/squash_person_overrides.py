import asyncio
import collections
import collections.abc
import contextlib
import json
import typing
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, UTC

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater

EPOCH = datetime(1970, 1, 1, 0, 0, tzinfo=UTC)


CREATE_TABLE_PERSON_DISTINCT_ID_OVERRIDES_JOIN = """
CREATE OR REPLACE TABLE {database}.person_distinct_id_overrides_join ON CLUSTER {cluster} (
    `team_id` Int64,
    `distinct_id` String,
    `person_id` UUID,
    `latest_version` Int64
)
ENGINE = Join(ANY, left, team_id, distinct_id)
AS
    SELECT
        team_id,
        distinct_id,
        argMax(person_id, version) AS person_id,
        max(version) AS latest_version
    FROM
        {database}.person_distinct_id_overrides
    WHERE
        ((length(%(team_ids)s) = 0) OR (team_id IN %(team_ids)s))
    GROUP BY
        team_id, distinct_id
SETTINGS
    max_execution_time = 0,
    max_memory_usage = 0,
    distributed_ddl_task_timeout = 0
"""

DROP_TABLE_PERSON_DISTINCT_ID_OVERRIDES_JOIN = """
DROP TABLE IF EXISTS {database}.person_distinct_id_overrides_join ON CLUSTER {cluster}
SETTINGS
    distributed_ddl_task_timeout = 0
"""

SUBMIT_UPDATE_EVENTS_WITH_PERSON_OVERRIDES = """
ALTER TABLE
    {database}.sharded_events
ON CLUSTER
    {cluster}
UPDATE
    person_id = joinGet('{database}.person_distinct_id_overrides_join', 'person_id', team_id, distinct_id)
IN PARTITION
    %(partition_id)s
WHERE
    (joinGet('{database}.person_distinct_id_overrides_join', 'person_id', team_id, distinct_id) != defaultValueOfTypeName('UUID'))
    AND ((length(%(team_ids)s) = 0) OR (team_id IN %(team_ids)s))
SETTINGS
    max_execution_time = 0
"""

MUTATIONS_IN_PROGRESS_IN_CLUSTER = """
SELECT mutation_id, is_done
FROM clusterAllReplicas('{cluster}', 'system', mutations)
WHERE table = %(table)s
AND database = '{database}'
AND command LIKE %(query)s
"""

NODES_ON_CLUSTER = """
SELECT
    count(*)
FROM
    system.clusters
WHERE
    cluster = '{cluster}'
"""

COUNT_TABLE_ON_CLUSTER = """
SELECT
    count(*)
FROM
    clusterAllReplicas('{cluster}', 'system', tables)
WHERE
    name = '{name}'
"""

KILL_MUTATION_IN_PROGRESS_ON_CLUSTER = """
KILL MUTATION ON CLUSTER {cluster}
WHERE is_done = 0
AND table = '{table}'
AND database = '{database}'
AND command LIKE %(query)s
"""

CREATE_TABLE_PERSON_DISTINCT_ID_OVERRIDES_JOIN_TO_DELETE = """
CREATE OR REPLACE TABLE {database}.person_distinct_id_overrides_join_to_delete ON CLUSTER {cluster}
ENGINE = Join(ANY, LEFT, team_id, distinct_id) AS
SELECT
    team_id,
    distinct_id,
    sum(person_id != joinGet('{database}.person_distinct_id_overrides_join', 'person_id', team_id, distinct_id)) AS total_not_override_person_id,
    sum(person_id = joinGet('{database}.person_distinct_id_overrides_join', 'person_id', team_id, distinct_id)) AS total_override_person_id
FROM
    {database}.sharded_events
WHERE
    (joinGet('{database}.person_distinct_id_overrides_join', 'person_id', team_id, distinct_id) != defaultValueOfTypeName('UUID'))
    AND ((length(%(team_ids)s) = 0) OR (team_id IN %(team_ids)s))
GROUP BY
    team_id, distinct_id
HAVING
    total_not_override_person_id = 0
    AND total_override_person_id > 0
SETTINGS
    max_execution_time = 0,
    max_memory_usage = 0,
    distributed_ddl_task_timeout = 0
"""

DROP_TABLE_PERSON_DISTINCT_ID_OVERRIDES_JOIN_TO_DELETE = """
DROP TABLE IF EXISTS {database}.person_distinct_id_overrides_join_to_delete ON CLUSTER {cluster}
SETTINGS
    distributed_ddl_task_timeout = 0
"""

# The two first where predicates are redundant as the join table already excludes any rows that don't match.
# However, there is no 'joinHas', and with 'joinGet' we are forced to grab a value.
SUBMIT_DELETE_PERSON_OVERRIDES = """
ALTER TABLE
    {database}.person_distinct_id_overrides
ON CLUSTER
    {cluster}
DELETE WHERE
    (joinGet('{database}.person_distinct_id_overrides_join_to_delete', 'total_not_override_person_id', team_id, distinct_id) = 0)
    AND (joinGet('{database}.person_distinct_id_overrides_join_to_delete', 'total_override_person_id', team_id, distinct_id) > 0)
    AND ((now() - _timestamp) > %(grace_period)s)
    AND (joinGet('{database}.person_distinct_id_overrides_join', 'latest_version', team_id, distinct_id) >= version)
SETTINGS
    max_execution_time = 0
"""

Table = collections.namedtuple("Table", ("name", "create_query", "drop_query"))
TABLES = {
    "person_distinct_id_overrides_join": Table(
        name="person_distinct_id_overrides_join",
        create_query=CREATE_TABLE_PERSON_DISTINCT_ID_OVERRIDES_JOIN,
        drop_query=DROP_TABLE_PERSON_DISTINCT_ID_OVERRIDES_JOIN,
    ),
    "person_distinct_id_overrides_join_to_delete": Table(
        name="person_distinct_id_overrides_join_to_delete",
        create_query=CREATE_TABLE_PERSON_DISTINCT_ID_OVERRIDES_JOIN_TO_DELETE,
        drop_query=DROP_TABLE_PERSON_DISTINCT_ID_OVERRIDES_JOIN_TO_DELETE,
    ),
}

Mutation = collections.namedtuple("Mutation", ("name", "table", "submit_query"))
MUTATIONS = {
    "update_events_with_person_overrides": Mutation(
        name="update_events_with_person_overrides",
        table="sharded_events",
        submit_query=SUBMIT_UPDATE_EVENTS_WITH_PERSON_OVERRIDES,
    ),
    "delete_person_overrides": Mutation(
        name="delete_person_overrides",
        table="person_distinct_id_overrides",
        submit_query=SUBMIT_DELETE_PERSON_OVERRIDES,
    ),
}


def parse_clickhouse_timestamp(s: str, tzinfo: timezone = UTC) -> datetime:
    """Parse a timestamp from ClickHouse."""
    return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=tzinfo)


def parse_count(response: bytes) -> int:
    """Parse the result of a single row SELECT count(*)."""
    line = response.decode("utf-8").splitlines()[0]
    count_str = line.strip()

    return int(count_str)


def parse_mutation_counts(response: bytes) -> tuple[int, int]:
    """Parse the count of mutations in progress and total mutations."""
    rows = []

    for line in response.decode("utf-8").splitlines():
        mutation_id, is_done = line.strip().split("\t")
        rows.append((mutation_id, int(is_done)))

    total_mutations = len(rows)
    mutations_in_progress = sum(row[1] == 0 for row in rows)

    return (mutations_in_progress, total_mutations)


def parse_mutation_command(mutation_query: str) -> str:
    """Parse a mutation query to try and extract a command from it.

    Mutations start with 'ALTER TABLE {table identifier} ON CLUSTER {cluster}'.
    The mutation command comes right after, and its one of 'UPDATE', 'DELETE WHERE', etc..., statements.
    So, we split and look for index 6 to find the start of the command:
    ["ALTER", "TABLE", "{table identifier}", "ON", "CLUSTER", "{cluster}", "{command}", ...].
                                                                            ^^^^^^^^^
    Also we get rid of any SETTINGS clause as these are not passed along as a command.

    Raises:
        ValueError: If we cannot parse the command. Usually this means the query is not an 'ALTER TABLE ... ON CLUSTER'.

    Examples:
        >>> parse_mutation_command("ALTER TABLE events ON CLUSTER UPDATE event = 'wow_event_name' SETTINGS max_execution_time = 0")
        "UPDATE event = 'wow_event_name'"
    """
    try:
        # Note: `split()` without `sep` takes care of all whitespace, so indent to your heart's content.
        query_command = " ".join(mutation_query.split()[6:])
        query_command = query_command.split("SETTINGS")[0].strip()
    except IndexError:
        raise ValueError("Provided query does not appear to be an 'ALTER TABLE ... ON CLUSTER' mutation")

    return query_command


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

    async with Heartbeater():
        async with get_client(mutations_sync=2) as clickhouse_client:
            await clickhouse_client.execute_query(
                optimize_query.format(database=settings.CLICKHOUSE_DATABASE, cluster=settings.CLICKHOUSE_CLUSTER)
            )
    activity.logger.info("Optimized person_distinct_id_overrides")


QueryParameters = dict[str, typing.Any]


@dataclass
class TableActivityInputs:
    """Inputs for activities that work with tables.

    Attributes:
        name: The table name which we are working with.
        exists: Whether we expect the table to exist or not.
        dry_run: Do not run the queries when `True`.
    """

    name: str
    query_parameters: QueryParameters
    exists: bool = True
    dry_run: bool = True


@activity.defn
async def create_table(inputs: TableActivityInputs) -> None:
    """Create one of the auxiliary tables in ClickHouse cluster.

    This activity will submit the 'CREATE TABLE' query for the corresponding table,
    but it will be created asynchronously in all cluster's nodes. Execute `wait_for_table`
    after this to ensure a table is available in the cluster before continuing.
    """
    from django.conf import settings

    create_table_query = TABLES[inputs.name].create_query.format(
        database=settings.CLICKHOUSE_DATABASE,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        cluster=settings.CLICKHOUSE_CLUSTER,
    )

    if inputs.dry_run is True:
        activity.logger.info("This is a DRY RUN so no table will be created.")
        activity.logger.debug("Query: %s", create_table_query)
        return

    async with Heartbeater():
        async with get_client() as clickhouse_client:
            await clickhouse_client.execute_query(create_table_query, query_parameters=inputs.query_parameters)

    activity.logger.info("Created JOIN table person_distinct_id_overrides_join_table")


@activity.defn
async def drop_table(inputs: TableActivityInputs) -> None:
    """Drop one of the auxiliary tables from ClickHouse cluster.

    We don't wait for tables to be dropped, and take a more optimistic approach
    that tables will be cleaned up. Execute `wait_for_table` after this to ensure
    a table is dropped in the cluster if ensuring clean-up is required.
    """
    from django.conf import settings

    drop_table_query = TABLES[inputs.name].drop_query.format(
        database=settings.CLICKHOUSE_DATABASE,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        cluster=settings.CLICKHOUSE_CLUSTER,
    )

    if inputs.dry_run is True:
        activity.logger.info("This is a DRY RUN so no table will be dropped.")
        activity.logger.debug("Query: %s", drop_table_query)
        return

    async with Heartbeater():
        async with get_client() as clickhouse_client:
            await clickhouse_client.execute_query(drop_table_query)

    activity.logger.info("Dropped table %s", inputs.name)


@activity.defn
async def wait_for_table(inputs: TableActivityInputs) -> None:
    """Wait for a table to be created or dropped on cluster.

    When running a 'CREATE TABLE ON CLUSTER', we have to ensure the table is created on all
    nodes before we can proceed. There are two ways of doing this: setting a high enough
    'distributed_ddl_task_timeout' and waiting on the query, or checking periodically if
    the tables are present on all nodes. The first option requires maintaining a long
    running connection, which is more vulnerable to connection drops and restarting without
    in detection of running queries would re-run a potentially expensive query.

    So, second option it is: This activity will query 'system.tables' to find if the table
    given by WaitForTableInputs.table is available in all nodes.

    The other use of this activity is to wait for a table to be dropped after a
    'DROP TABLE ON CLUSTER' query is submitted. Although less critical from the Squash Workflow's
    perspective, it is important we clean-up after ourselves.
    """
    from django.conf import settings

    goal = "exist" if inputs.exists else "not exist"
    activity.logger.info("Waiting for table %s in cluster to %s", inputs.name, goal)

    if inputs.dry_run is True:
        activity.logger.info("This is a DRY RUN so nothing will be waited for.")
        return

    async with get_client() as clickhouse_client:
        response = await clickhouse_client.read_query(
            NODES_ON_CLUSTER.format(
                database=settings.CLICKHOUSE_DATABASE,
                cluster=settings.CLICKHOUSE_CLUSTER,
            ),
        )
        count_of_nodes = parse_count(response)

        try:
            while True:
                activity.heartbeat()

                response = await clickhouse_client.read_query(
                    COUNT_TABLE_ON_CLUSTER.format(
                        database=settings.CLICKHOUSE_DATABASE,
                        cluster=settings.CLICKHOUSE_CLUSTER,
                        name=inputs.name,
                    ),
                )

                count_of_tables = parse_count(response)

                is_done = (inputs.exists and count_of_tables >= count_of_nodes) or (
                    not inputs.exists and count_of_tables == 0
                )
                if is_done:
                    break

                activity.logger.info(
                    "Still waiting for table %s in cluster to %s: %s/%s",
                    inputs.name,
                    goal,
                    count_of_tables,
                    count_of_nodes,
                )

                await asyncio.sleep(5)

        except asyncio.CancelledError:
            if inputs.exists is False:
                activity.logger.warning(
                    "Activity has been cancelled, could not wait for table %s to be dropped",
                    inputs.name,
                )

                raise

            activity.logger.warning(
                "Activity has been cancelled, attempting to drop any partially or fully created %s tables",
                inputs.name,
            )

            await clickhouse_client.execute_query(
                TABLES[inputs.name].drop_query.format(
                    database=settings.CLICKHOUSE_DATABASE,
                    cluster=settings.CLICKHOUSE_CLUSTER,
                ),
            )
            raise

    activity.logger.info("Waiting done, table %s in cluster does %s", inputs.name, goal)


@contextlib.asynccontextmanager
async def manage_table(
    table_name: str, dry_run: bool, query_parameters: QueryParameters
) -> collections.abc.AsyncGenerator[None, None]:
    """A context manager to create ans subsequently drop a table."""
    table_activity_inputs = TableActivityInputs(
        name=table_name,
        query_parameters=query_parameters,
        dry_run=dry_run,
        exists=True,
    )
    await workflow.execute_activity(
        create_table,
        table_activity_inputs,
        start_to_close_timeout=timedelta(minutes=5),
        retry_policy=RetryPolicy(maximum_attempts=1),
        heartbeat_timeout=timedelta(minutes=1),
    )

    await workflow.execute_activity(
        wait_for_table,
        table_activity_inputs,
        start_to_close_timeout=timedelta(hours=6),
        retry_policy=RetryPolicy(
            maximum_attempts=0, initial_interval=timedelta(seconds=20), maximum_interval=timedelta(minutes=2)
        ),
        heartbeat_timeout=timedelta(minutes=2),
    )

    try:
        yield
    finally:
        await workflow.execute_activity(
            drop_table,
            table_activity_inputs,
            start_to_close_timeout=timedelta(hours=1),
            retry_policy=RetryPolicy(
                maximum_attempts=2, initial_interval=timedelta(seconds=5), maximum_interval=timedelta(seconds=10)
            ),
            heartbeat_timeout=timedelta(minutes=1),
        )

        table_activity_inputs.exists = False
        await workflow.execute_activity(
            wait_for_table,
            table_activity_inputs,
            # Assuming clean-up should be relatively fast.
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(
                maximum_attempts=2, initial_interval=timedelta(seconds=5), maximum_interval=timedelta(seconds=10)
            ),
            heartbeat_timeout=timedelta(seconds=20),
        )


@dataclass
class MutationActivityInputs:
    """Inputs for activities that work with mutations.

    Attributes:
        name: The mutation name which we are working with.
        query_parameters: Any query parameters needed for the mutation query.
        dry_run: Do not run the queries when True.
    """

    name: str
    query_parameters: QueryParameters
    dry_run: bool = True


@activity.defn
async def submit_mutation(inputs: MutationActivityInputs) -> str:
    """Execute a mutation ('ALTER TABLE') in ClickHouse.

    This activity will submit only submit the mutation to be executed asynchronously on the
    whole cluster. We will not wait for it (use `wait_for_mutation` for that).
    """
    from django.conf import settings

    activity.logger.info("Submitting mutation %s", inputs.name)

    query = MUTATIONS[inputs.name].submit_query.format(
        database=settings.CLICKHOUSE_DATABASE,
        cluster=settings.CLICKHOUSE_CLUSTER,
        **inputs.query_parameters,
    )

    async with get_client() as clickhouse_client:
        prepared_query = clickhouse_client.prepare_query(query, inputs.query_parameters)

        if inputs.dry_run is True:
            activity.logger.info("This is a DRY RUN so mutation %s will not be submitted.", inputs.name)
            activity.logger.debug(prepared_query)

            return prepared_query

        # Best cancellation scenario: It fires off before we begin a new mutation and there is nothing to cancel.
        activity.heartbeat()

        await clickhouse_client.execute_query(prepared_query)

    activity.logger.info("Mutation %s submitted", inputs.name)

    return prepared_query


@activity.defn
async def wait_for_mutation(inputs: MutationActivityInputs) -> None:
    """Wait for a mutation to finish.

    We wait for the mutation to be done in the whole cluster.

    WARNING: To check for running mutations we select from the 'system.mutations' table filtering
    by 'command'. The 'command' field is the sql statement after 'ALTER TABLE', for example:
    'UPDATE ...' or 'DELETE WHERE ...'. However, this command is formatted by  ClickHouse when written
    to 'system.mutations', and ClickHouse's formatting may differ from the way you have written
    the query. For example: ClickHouse formatting sometimes adds additional parantheses, or changes
    the casing of functions. In that situation, using an exact filter predicate on 'command' will
    not return any rows, and we won't be able to wait for your mutation. I recommend manually
    running 'EXPLAIN SYNTAX' to get the formatted 'ALTER TABLE' query and then copying that as the
    mutation query at the top of this file, replacing any placeholders that we fill in here.
    """
    from django.conf import settings

    activity.logger.info("Waiting for mutation  %s", inputs.name)

    if inputs.dry_run is True:
        activity.logger.info("This is a DRY RUN so nothing will be waited for.")
        return

    mutation = MUTATIONS[inputs.name]
    submit_query = mutation.submit_query.format(
        database=settings.CLICKHOUSE_DATABASE,
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
    async with Heartbeater():
        async with get_client() as clickhouse_client:
            prepared_submit_query = clickhouse_client.prepare_query(submit_query, inputs.query_parameters)
            query_command = parse_mutation_command(prepared_submit_query)

            try:
                while True:
                    response = await clickhouse_client.read_query(
                        MUTATIONS_IN_PROGRESS_IN_CLUSTER.format(
                            database=settings.CLICKHOUSE_DATABASE,
                            cluster=settings.CLICKHOUSE_CLUSTER,
                        ),
                        query_parameters={"query": query_command, "table": mutation.table},
                    )

                    mutations_in_progress, _ = parse_mutation_counts(response)

                    if mutations_in_progress == 0:
                        break

                    activity.logger.info("Still waiting for mutation %s", inputs.name)

                    await asyncio.sleep(5)

            except asyncio.CancelledError:
                activity.logger.warning(
                    "Activity has been cancelled, attempting to kill in progress mutation %s",
                    inputs.name,
                )

                await clickhouse_client.execute_query(
                    KILL_MUTATION_IN_PROGRESS_ON_CLUSTER.format(
                        database=settings.CLICKHOUSE_DATABASE,
                        cluster=settings.CLICKHOUSE_CLUSTER,
                        table=mutation.table,
                    ),
                    query_parameters={"query": query_command, "table": mutation.table},
                )
                raise

            else:
                activity.logger.info("Mutation finished %s", inputs.name)


async def submit_and_wait_for_mutation(
    mutation_name: str,
    mutation_parameters: QueryParameters,
    dry_run: bool,
) -> None:
    """Submit and wait for a mutation in ClickHouse."""
    mutation_activity_inputs = MutationActivityInputs(
        name=mutation_name,
        query_parameters=mutation_parameters,
        dry_run=dry_run,
    )
    await workflow.execute_activity(
        submit_mutation,
        mutation_activity_inputs,
        start_to_close_timeout=timedelta(minutes=2),
        retry_policy=RetryPolicy(maximum_attempts=1),
        heartbeat_timeout=timedelta(seconds=10),
    )

    await workflow.execute_activity(
        wait_for_mutation,
        mutation_activity_inputs,
        start_to_close_timeout=timedelta(hours=6),
        retry_policy=RetryPolicy(
            maximum_attempts=0, initial_interval=timedelta(seconds=20), maximum_interval=timedelta(minutes=2)
        ),
        heartbeat_timeout=timedelta(minutes=2),
    )


@dataclass
class SquashPersonOverridesInputs:
    """Inputs for the SquashPersonOverrides workflow.

    Attributes:
        team_ids: List of team ids to squash. If `None`, will squash all.
        partition_ids: Partitions to squash, preferred over `last_n_months`.
        last_n_months: Execute the squash on the last n month partitions.
        offset: Start from offset month when generating partitions to squash with `last_n_months`
        delete_grace_period_seconds: Number of seconds until an override can be deleted. This grace
            period works on top of checking if the override was applied to all partitions. Defaults
            to 24h.
        dry_run: If True, queries that mutate or delete data will not execute and instead will be logged.
    """

    team_ids: list[int] = field(default_factory=list)
    partition_ids: list[str] | None = None
    last_n_months: int = 1
    offset: int = 0
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

    def iter_last_n_months(self) -> collections.abc.Iterator[date]:
        """Iterate over beginning of the month dates of the last N months.

        If `self.offset` is 0, then the first day of the current month will be the
        first month yielded. Otherwise, `self.offset` will be subtracted from the
        current month to land on the first month to yield.
        """
        now = date.today()
        start_month = (now.month - self.offset) % 12
        start_year = now.year + (now.month - self.offset) // 12
        current_date = date(year=start_year, month=start_month, day=1)

        for _ in range(0, self.last_n_months):
            current_date = current_date.replace(day=1)

            yield current_date

            current_date = current_date - timedelta(days=1)


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

    1. Build a JOIN table from person_distinct_id_overrides.
    2. For each partition issue an ALTER TABLE UPDATE. This query uses joinGet
        to efficiently find the override for each (team_id, distinct_id) pair
        in the JOIN table we built in 1.
    3. Delete from person_distinct_id_overrides any overrides that were squashed
        and are past the grace period. We construct an auxiliary JOIN table to
        identify the persons that can be deleted.
    4. Clean up both auxiliary JOIN tables once done.
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
            start_to_close_timeout=timedelta(hours=1),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=20)),
            heartbeat_timeout=timedelta(minutes=1),
        )

        table_query_parameters = {
            "team_ids": list(inputs.team_ids),
        }
        async with manage_table("person_distinct_id_overrides_join", inputs.dry_run, table_query_parameters):
            for partition_id in inputs.iter_partition_ids():
                mutation_parameters: QueryParameters = {
                    "partition_id": partition_id,
                    "team_ids": list(inputs.team_ids),
                }
                await submit_and_wait_for_mutation(
                    "update_events_with_person_overrides",
                    mutation_parameters,
                    inputs.dry_run,
                )
                workflow.logger.info("Squash finished for all requested partitions, now deleting person overrides")

            async with manage_table(
                "person_distinct_id_overrides_join_to_delete", inputs.dry_run, table_query_parameters
            ):
                delete_mutation_parameters: QueryParameters = {
                    "partition_ids": list(inputs.iter_partition_ids()),
                    "grace_period": inputs.delete_grace_period_seconds,
                }
                await submit_and_wait_for_mutation(
                    "delete_person_overrides",
                    delete_mutation_parameters,
                    inputs.dry_run,
                )

        workflow.logger.info("Squash workflow is done 🎉")
