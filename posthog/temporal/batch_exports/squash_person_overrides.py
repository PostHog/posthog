import asyncio
import collections
import collections.abc
import contextlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import NamedTuple

from django.conf import settings
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater


# table management


@dataclass
class SnapshotTableInfo:
    """Inputs for activities that work with tables.

    Attributes:
        name: The table name which we are working with.
    """

    name: str

    async def create_table(self, clickhouse_client):
        return await clickhouse_client.execute_query(
            f"""
            CREATE OR REPLACE TABLE {settings.CLICKHOUSE_DATABASE}.{self.name}
                ON CLUSTER {settings.CLICKHOUSE_CLUSTER}
            (
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
                    {settings.CLICKHOUSE_DATABASE}.person_distinct_id_overrides
                GROUP BY
                    team_id, distinct_id
            SETTINGS
                max_execution_time = 0,
                max_memory_usage = 0,
                distributed_ddl_task_timeout = 0
            """
        )

    async def drop_table(self, clickhouse_client):
        return await clickhouse_client.execute_query(
            f"""
            DROP TABLE IF EXISTS {settings.CLICKHOUSE_DATABASE}.{self.name}
                ON CLUSTER {settings.CLICKHOUSE_CLUSTER}
            SETTINGS distributed_ddl_task_timeout = 0
            """
        )


@activity.defn
async def create_snapshot_table(inputs: SnapshotTableInfo) -> None:
    """Create one of the auxiliary tables in ClickHouse cluster.

    This activity will submit the 'CREATE TABLE' query for the corresponding table,
    but it will be created asynchronously in all cluster's nodes. Execute `wait_for_table`
    after this to ensure a table is available in the cluster before continuing.
    """

    async with Heartbeater(), get_client() as clickhouse_client:
        await inputs.create_table(clickhouse_client)

    activity.logger.info("Created table %s", inputs.name)


@activity.defn
async def drop_snapshot_table(inputs: SnapshotTableInfo) -> None:
    """Drop one of the auxiliary tables from ClickHouse cluster.

    We don't wait for tables to be dropped, and take a more optimistic approach
    that tables will be cleaned up. Execute `wait_for_table` after this to ensure
    a table is dropped in the cluster if ensuring clean-up is required.
    """

    async with Heartbeater(), get_client() as clickhouse_client:
        await inputs.drop_table(clickhouse_client)

    activity.logger.info("Dropped table %s", inputs.name)


@dataclass
class WaitForTableInputs:
    name: str
    should_exist: bool


@activity.defn
async def wait_for_table(inputs: WaitForTableInputs) -> None:
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
    goal = "exist" if inputs.should_exist else "not exist"
    activity.logger.info("Waiting for table %s in cluster to %s", inputs.name, goal)

    async with get_client() as clickhouse_client:
        try:
            while True:
                activity.heartbeat()

                response = await clickhouse_client.read_query(
                    """
                    SELECT
                        hostname() as hostname,
                        countIf(database = %(database)s and name = %(name)s) > 0 as has_table
                    FROM clusterAllReplicas(%(cluster)s, 'system', tables)
                    GROUP BY hostname
                    FORMAT JSONCompact
                    """,
                    {
                        "cluster": settings.CLICKHOUSE_CLUSTER,
                        "database": settings.CLICKHOUSE_DATABASE,
                        "name": inputs.name,
                    },
                )
                host_status_map = {
                    hostname: has_table if inputs.should_exist else not has_table
                    for hostname, has_table in json.loads(response)["data"]
                }
                if all(host_status_map.values()):
                    break

                activity.logger.info(
                    "Still waiting for table %s in cluster to %s on %r (%s/%s ready)",
                    inputs.name,
                    goal,
                    {host for host, is_ready in host_status_map.items() if not is_ready},
                    sum(host_status_map.values()),
                    len(host_status_map),
                )

                await asyncio.sleep(5)

        except asyncio.CancelledError:
            if inputs.should_exist is False:
                activity.logger.warning(
                    "Activity has been cancelled, could not wait for table %s to be dropped",
                    inputs.name,
                )
                raise

            activity.logger.warning(
                "Activity has been cancelled, attempting to drop any partially or fully created %s tables",
                inputs.name,
            )

            await inputs.drop_table(clickhouse_client)
            raise

    activity.logger.info("Waiting done, table %s in cluster does %s", inputs.name, goal)


@contextlib.asynccontextmanager
async def manage_snapshot_table(snapshot_table: SnapshotTableInfo) -> collections.abc.AsyncGenerator[None, None]:
    """A context manager to create ans subsequently drop a table."""
    await workflow.execute_activity(
        create_snapshot_table,
        snapshot_table,
        start_to_close_timeout=timedelta(minutes=5),
        retry_policy=RetryPolicy(maximum_attempts=1),
        heartbeat_timeout=timedelta(minutes=1),
    )

    await workflow.execute_activity(
        wait_for_table,
        WaitForTableInputs(name=snapshot_table.name, should_exist=True),
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
            drop_snapshot_table,
            snapshot_table,
            start_to_close_timeout=timedelta(hours=1),
            retry_policy=RetryPolicy(
                maximum_attempts=2, initial_interval=timedelta(seconds=5), maximum_interval=timedelta(seconds=10)
            ),
            heartbeat_timeout=timedelta(minutes=1),
        )
        await workflow.execute_activity(
            wait_for_table,
            WaitForTableInputs(name=snapshot_table.name, should_exist=False),
            # Assuming clean-up should be relatively fast.
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(
                maximum_attempts=2, initial_interval=timedelta(seconds=5), maximum_interval=timedelta(seconds=10)
            ),
            heartbeat_timeout=timedelta(seconds=20),
        )


# mutation management


class Mutation(NamedTuple):
    name: str
    table: str
    submit_query: str


@dataclass
class MutationActivityInputs:
    """Inputs for activities that work with mutations.

    Attributes:
        name: The mutation name which we are working with.
    """

    name: str


@activity.defn
async def submit_mutation(inputs: MutationActivityInputs) -> str:
    """Execute a mutation ('ALTER TABLE') in ClickHouse.

    This activity will submit only submit the mutation to be executed asynchronously on the
    whole cluster. We will not wait for it (use `wait_for_mutation` for that).
    """
    activity.logger.info("Submitting mutation %s", inputs.name)

    query = MUTATIONS[inputs.name].submit_query.format(
        database=settings.CLICKHOUSE_DATABASE,
        cluster=settings.CLICKHOUSE_CLUSTER,
    )

    async with get_client() as clickhouse_client:
        prepared_query = clickhouse_client.prepare_query(query)

        # Best cancellation scenario: It fires off before we begin a new mutation and there is nothing to cancel.
        activity.heartbeat()

        await clickhouse_client.execute_query(prepared_query)

    activity.logger.info("Mutation %s submitted", inputs.name)

    return prepared_query


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
    activity.logger.info("Waiting for mutation  %s", inputs.name)

    mutation = MUTATIONS[inputs.name]
    submit_query = mutation.submit_query.format(
        database=settings.CLICKHOUSE_DATABASE,
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
    async with Heartbeater():
        async with get_client() as clickhouse_client:
            prepared_submit_query = clickhouse_client.prepare_query(submit_query)
            query_command = parse_mutation_command(prepared_submit_query)

            try:
                while True:
                    response = await clickhouse_client.read_query(
                        """
                        SELECT mutation_id, is_done
                        FROM clusterAllReplicas(%(cluster)s, 'system', mutations)
                        WHERE table = %(table)s
                        AND database = %(database)s
                        AND command LIKE %(query)s
                        """,
                        query_parameters={
                            "cluster": settings.CLICKHOUSE_CLUSTER,
                            "database": settings.CLICKHOUSE_DATABASE,
                            "query": query_command,
                            "table": mutation.table,
                        },
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
                    f"""
                    KILL MUTATION ON CLUSTER {settings.CLICKHOUSE_CLUSTER}
                    WHERE is_done = 0
                    AND table = %(table)s
                    AND database = %(database)s
                    AND command LIKE %(query)s
                    """,
                    query_parameters={
                        "database": settings.CLICKHOUSE_DATABASE,
                        "query": query_command,
                        "table": mutation.table,
                    },
                )
                raise

            else:
                activity.logger.info("Mutation finished %s", inputs.name)


async def submit_and_wait_for_mutation(
    mutation_name: str,
) -> None:
    """Submit and wait for a mutation in ClickHouse."""
    mutation_activity_inputs = MutationActivityInputs(name=mutation_name)

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


# core workflow logic

SUBMIT_UPDATE_EVENTS_WITH_PERSON_OVERRIDES = """
ALTER TABLE
    {database}.sharded_events
ON CLUSTER
    {cluster}
UPDATE
    person_id = joinGet('{database}.person_distinct_id_overrides_join', 'person_id', team_id, distinct_id)
WHERE
    (joinGet('{database}.person_distinct_id_overrides_join', 'person_id', team_id, distinct_id) != defaultValueOfTypeName('UUID'))
SETTINGS
    max_execution_time = 0
"""

# The two first where predicates are redundant as the join table already excludes any rows that don't match.
# However, there is no 'joinHas', and with 'joinGet' we are forced to grab a value.
SUBMIT_DELETE_PERSON_OVERRIDES = """
ALTER TABLE
    {database}.person_distinct_id_overrides
ON CLUSTER
    {cluster}
DELETE WHERE
    joinGet('{database}.person_distinct_id_overrides_join', 'latest_version', team_id, distinct_id) >= version
SETTINGS
    max_execution_time = 0
"""

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


@dataclass
class SquashPersonOverridesInputs:
    """Inputs for the SquashPersonOverrides workflow."""


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
    2. Issue an ALTER TABLE UPDATE. This query uses joinGet
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

        snapshot_table = SnapshotTableInfo("person_distinct_id_overrides_join")
        async with manage_snapshot_table(snapshot_table):
            await submit_and_wait_for_mutation("update_events_with_person_overrides")
            workflow.logger.info("Squash finished, now deleting person overrides")

            await submit_and_wait_for_mutation("delete_person_overrides")

        workflow.logger.info("Squash workflow is done 🎉")
