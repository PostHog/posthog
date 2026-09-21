import uuid
import datetime
from dataclasses import dataclass
from functools import partial

import dagster
import pydantic
from clickhouse_driver import Client

from posthog import settings
from posthog.clickhouse.cluster import ClickhouseCluster, MutationWaiter, wait_for_mutations_on_shards
from posthog.dags.common import JobOwners
from posthog.dags.common.overrides_manager import OverridesSnapshotDictionary, OverridesSnapshotTable
from posthog.dags.common.staged_dictionary import (
    StagedDictionary,
    create_on_every_cluster,
    load_and_verify_on_every_cluster,
)
from posthog.dataclasses import frozen
from posthog.models.deletion_targets import (
    EVENTS_TARGETS,
    FLAG_EVALUATIONS,
    DeletionTarget,
    resolve_placements,
    sweep_clusters,
)
from posthog.models.person.sql import PERSON_DISTINCT_ID_OVERRIDES_TABLE

# Every table the squash rewrites person_id on. sharded_flag_evaluations is not an events table,
# but it stamps rows with the same person_id, and a person deletion matches the deleted person's
# uuid against that column. A row a merge left on the absorbed person therefore matches nothing and
# survives until its partition ages out, so the squash has to move it too.
#
# Deliberately not PERSONAL_DATA_TARGETS: registering a table for deletion should not silently make
# it a squash target as well.
SQUASH_TARGETS = (*EVENTS_TARGETS, FLAG_EVALUATIONS)

# How far back a snapshot reaches, so every override it selects has been written and replicated
# everywhere by the time the rewrite joins it.
SNAPSHOT_LAG_DAYS = 2


def _squash_clusters(cluster: ClickhouseCluster) -> list[ClickhouseCluster]:
    """Every cluster the person_id rewrite dispatches to, the handle in hand first.

    The rewrite joins the snapshot dictionary, so the dictionary has to exist on each of them.
    """
    return sweep_clusters(cluster, SQUASH_TARGETS)


@dataclass
class PersonOverridesSnapshotTable(OverridesSnapshotTable):
    id: uuid.UUID

    @property
    def name(self) -> str:
        return f"person_distinct_id_overrides_snapshot_{self.id.hex}"

    def create(self, client: Client) -> None:
        client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.qualified_name} (team_id Int64, distinct_id String, person_id UUID, version Int64)
            ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/{self.qualified_name}', '{{replica}}-{{shard}}', version)
            ORDER BY (team_id, distinct_id)
            """
        )

    def populate(self, client: Client, timestamp: str, limit: int | None = None) -> None:
        # NOTE: this is theoretically subject to replication lag and accuracy of this result is not a guarantee
        # this could optionally support truncate as a config option if necessary to reset the table state, or
        # force an optimize after insertion to compact the table before dictionary insertion (if that's even needed)
        [[count]] = client.execute(f"SELECT count() FROM {self.qualified_name}")
        assert count == 0

        limit_clause = f"LIMIT {limit}" if limit else ""

        client.execute(
            f"""
            INSERT INTO {self.qualified_name} (team_id, distinct_id, person_id, version)
            SELECT team_id, distinct_id, argMax(person_id, version), max(version)
            FROM {settings.CLICKHOUSE_DATABASE}.{PERSON_DISTINCT_ID_OVERRIDES_TABLE}
            WHERE _timestamp < %(timestamp)s
            GROUP BY team_id, distinct_id
            {limit_clause}
            """,
            {"timestamp": timestamp},
            settings={
                "optimize_aggregation_in_order": 1,  # slows down the query, but reduces memory consumption dramatically
            },
        )


@frozen
class PersonOverridesSnapshotDictionary(OverridesSnapshotDictionary):
    source: PersonOverridesSnapshotTable

    def staged(self) -> StagedDictionary:
        return StagedDictionary(
            key=f"{self.name}.parquet",
            columns="team_id, distinct_id, person_id, version",
            structure="team_id Int64, distinct_id String, person_id UUID, version Int64",
        )

    @property
    def query(self) -> str:
        return f"SELECT team_id, distinct_id, person_id, version FROM {self.source.qualified_name}"

    def create(
        self,
        client: Client,
        shards: int,
        max_execution_time: int,
        max_memory_usage: int,
        query: str | None = None,
    ) -> None:
        # A host that cannot see the snapshot table reads the staged object instead, which is a
        # query rather than a table name.
        source = "QUERY %(query)s" if query else "TABLE %(table)s"
        client.execute(
            f"""
            CREATE DICTIONARY IF NOT EXISTS {self.qualified_name} (
                team_id Int64,
                distinct_id String,
                person_id UUID,
                version Int64
            )
            PRIMARY KEY team_id, distinct_id
            SOURCE(CLICKHOUSE(DB %(database)s {source} USER %(user)s PASSWORD %(password)s))
            LAYOUT(COMPLEX_KEY_HASHED(SHARDS {shards}))
            LIFETIME(0)
            SETTINGS(max_execution_time={max_execution_time}, max_memory_usage={max_memory_usage})
            """,
            {
                "database": settings.CLICKHOUSE_DATABASE,
                "table": self.source.name,
                "query": query,
                "user": settings.CLICKHOUSE_USER,
                "password": settings.CLICKHOUSE_PASSWORD,
            },
        )

    def get_checksum(self, client: Client):
        results = client.execute(
            f"""
             SELECT groupBitXor(row_checksum) AS table_checksum
             FROM (SELECT cityHash64(*) AS row_checksum FROM {self.qualified_name} ORDER BY team_id, distinct_id)
             """
        )
        [[checksum]] = results
        return checksum

    @property
    def update_commands(self):
        return {
            "UPDATE person_id = dictGet(%(name)s, 'person_id', (team_id, distinct_id)) WHERE dictHas(%(name)s, (team_id, distinct_id))"
        }

    @property
    def overrides_table(self):
        return PERSON_DISTINCT_ID_OVERRIDES_TABLE

    @property
    def overrides_deletes_predicate(self):
        return "isNotNull(dictGetOrNull(%(name)s, 'version', (team_id, distinct_id)) as snapshot_version) AND snapshot_version >= version"


# Snapshot Table Management


@dagster.op
def create_snapshot_table(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> PersonOverridesSnapshotTable:
    """Create the snapshot table on all hosts in the cluster."""
    table = PersonOverridesSnapshotTable(id=uuid.UUID(context.run.run_id))
    cluster.map_all_hosts(table.create).result()
    return table


class PopulateSnapshotTableConfig(dagster.Config):
    """
    Configuration for creating and populating the initial snapshot table.
    """

    timestamp: str = pydantic.Field(
        description="The upper bound (non-inclusive) timestamp used when selecting person overrides to be squashed. The "
        "value can be provided in any format that is can be parsed by ClickHouse. This value should be far enough in "
        "the past that there is no reasonable likelihood that events or overrides prior to this time have not yet been "
        "written to the database and replicated to all hosts in the cluster.",
        # A factory, not a literal: a literal here is evaluated when the module is imported, so
        # every run on a long-lived code server would reuse the window the first run consumed.
        default_factory=lambda: (datetime.datetime.now() - datetime.timedelta(days=SNAPSHOT_LAG_DAYS)).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    )
    limit: int | None = pydantic.Field(
        description="The number of rows to include in the snapshot. If provided, this can be used to limit the total "
        "amount of memory consumed by the squash process during execution.",
        default=None,
    )


@dagster.op
def populate_snapshot_table(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    table: PersonOverridesSnapshotTable,
    config: PopulateSnapshotTableConfig,
) -> PersonOverridesSnapshotTable:
    """Fill the snapshot data with the selected overrides based on the configuration timestamp."""
    cluster.any_host(partial(table.populate, timestamp=config.timestamp, limit=config.limit)).result()
    return table


@dagster.op
def wait_for_snapshot_table_replication(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    table: PersonOverridesSnapshotTable,
) -> PersonOverridesSnapshotTable:
    """Wait for the snapshot table data to be replicated to all hosts in the cluster."""
    cluster.map_all_hosts(table.sync).result()
    return table


# Snapshot Dictionary Management


class SnapshotDictionaryConfig(dagster.Config):
    shards: int = pydantic.Field(
        default=16,
        description="The number of shards to be used when building the dictionary. Using larger values can speed up the "
        "creation process. See the ClickHouse documentation for more information.",
    )
    max_execution_time: int = pydantic.Field(
        default=0,
        description="The maximum amount of time to wait for the dictionary to be loaded before considering the operation "
        "a failure, or 0 to wait an unlimited amount of time.",
    )
    max_memory_usage: int = pydantic.Field(
        default=0,
        description="The maximum amount of memory to use for the dictionary, or 0 to use an unlimited amount.",
    )


@dagster.op
def create_snapshot_dictionary(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    config: SnapshotDictionaryConfig,
    table: PersonOverridesSnapshotTable,
) -> PersonOverridesSnapshotDictionary:
    """Create the snapshot dictionary on every cluster the person_id rewrite will run on."""
    dictionary = PersonOverridesSnapshotDictionary(source=table)
    create_on_every_cluster(
        context,
        _squash_clusters(cluster),
        dictionary,
        shards=config.shards,
        max_execution_time=config.max_execution_time,
        max_memory_usage=config.max_memory_usage,
    )
    return dictionary


class GetExistingDictionaryConfig(dagster.Config):
    id: str = pydantic.Field(description="The run ID of the original run that created the dictionary.")


@dagster.op
def get_existing_dictionary_for_run_id(
    config: GetExistingDictionaryConfig,
) -> PersonOverridesSnapshotDictionary:
    """
    Provides a handle to a snapshot dictionary based on the original run ID.

    This does not create the dictionary or ensure that it or any of its dependencies exist.
    """
    table = PersonOverridesSnapshotTable(uuid.UUID(config.id))
    return PersonOverridesSnapshotDictionary(source=table)


@dagster.op
def load_and_verify_snapshot_dictionary(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    dictionary: PersonOverridesSnapshotDictionary,
) -> PersonOverridesSnapshotDictionary:
    """Load the dictionary on every host of every cluster it will be joined on, and verify it."""
    load_and_verify_on_every_cluster(_squash_clusters(cluster), dictionary)
    return dictionary


# Mutation Management


def _build_person_id_update_mutations_op(name: str, targets: tuple[DeletionTarget, ...]) -> dagster.OpDefinition:
    """Build the person_id rewrite op for a fixed set of targets.

    The targets are bound here rather than read from run config, so a run cannot point the rewrite
    at a table its job was never meant to touch.
    """

    @dagster.op(name=name)
    def run_mutations(
        cluster: dagster.ResourceParam[ClickhouseCluster],
        dictionary: PersonOverridesSnapshotDictionary,
    ) -> PersonOverridesSnapshotDictionary:
        """Rewrite person_id on every target, each on the cluster whose shards carry it.

        A target's storage table can sit on a cluster whose shards only its own handle enumerates,
        so the dispatch follows the resolved placement rather than the handle in hand. Skipping one
        would leave its rows on a person_id this run squashed away.
        """
        enqueued: list[tuple[ClickhouseCluster, dict[int, MutationWaiter]]] = []
        for placement in resolve_placements(cluster, targets):
            runner = dictionary.update_mutation_runner_for(placement.target.data_table)
            enqueued.append((placement.cluster, runner.enqueue_on_shards(placement.cluster)))

        # Every mutation is already in flight, so these waits overlap and cost the longest rather
        # than their sum. The capacity wait inside enqueue_on_shards is still per table and serial.
        for handle, shard_mutations in enqueued:
            wait_for_mutations_on_shards(handle, shard_mutations)
        return dictionary

    return run_mutations


run_person_id_update_mutations = _build_person_id_update_mutations_op("run_person_id_update_mutations", SQUASH_TARGETS)
run_flag_evaluations_person_id_update_mutations = _build_person_id_update_mutations_op(
    "run_flag_evaluations_person_id_update_mutations", (FLAG_EVALUATIONS,)
)


@dagster.op
def start_overrides_delete_mutations(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    dictionary: PersonOverridesSnapshotDictionary,
) -> tuple[PersonOverridesSnapshotDictionary, MutationWaiter]:
    """Start the mutation to remove overrides contained within the snapshot from the overrides table."""
    mutation = cluster.any_host(dictionary.overrides_delete_mutation_runner).result()
    return (dictionary, mutation)


@dagster.op
def wait_for_overrides_delete_mutations(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    inputs: tuple[PersonOverridesSnapshotDictionary, MutationWaiter],
) -> PersonOverridesSnapshotDictionary:
    """Wait for all hosts to complete the mutation to remove overrides contained within the snapshot from the overrides table."""
    [dictionary, mutation] = inputs
    cluster.map_all_hosts(mutation.wait).result()
    return dictionary


# Cleanup


@dagster.op
def drop_snapshot_dictionary(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    dictionary: PersonOverridesSnapshotDictionary,
) -> PersonOverridesSnapshotTable:
    """Drop the snapshot dictionary on all hosts of every cluster it was created on."""
    for handle in _squash_clusters(cluster):
        handle.map_all_hosts(dictionary.drop).result()
    return dictionary.source


@dagster.op
def drop_snapshot_table(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    table: PersonOverridesSnapshotTable,
) -> None:
    """Drop the snapshot table on all hosts."""
    cluster.map_all_hosts(table.drop).result()


def cleanup_snapshot_resources(dictionary: PersonOverridesSnapshotDictionary) -> None:
    return drop_snapshot_table(drop_snapshot_dictionary(dictionary))


# Job Definition


# Both jobs rewrite person_id on flag_evaluations from their own snapshot. The capacity wait in
# MutationRunner keeps two mutations off a table at once, but it does not order the runs: a job
# parked on another target's capacity can enqueue its flag_evaluations mutation after a later run
# already finished one. This key is what a run-queue limit of 1 attaches to in Dagster deployment
# settings; deletes_job_concurrency is the matched example. The key alone enforces nothing.
PERSON_ID_REWRITE_CONCURRENCY_TAGS = {
    "owner": JobOwners.TEAM_CLICKHOUSE.value,
    "person_id_rewrite_concurrency": "v1",
}


@dagster.job(tags=PERSON_ID_REWRITE_CONCURRENCY_TAGS)
def squash_person_overrides():
    prepared_snapshot_table = wait_for_snapshot_table_replication(populate_snapshot_table(create_snapshot_table()))
    prepared_dictionary = load_and_verify_snapshot_dictionary(create_snapshot_dictionary(prepared_snapshot_table))
    dictionary_after_person_id_update_mutations = run_person_id_update_mutations(prepared_dictionary)
    dictionary_after_override_delete_mutations = wait_for_overrides_delete_mutations(
        start_overrides_delete_mutations(dictionary_after_person_id_update_mutations)
    )
    cleanup_snapshot_resources(dictionary_after_override_delete_mutations)


@dagster.job(tags=PERSON_ID_REWRITE_CONCURRENCY_TAGS)
def rewrite_flag_evaluations_person_id():
    """Apply the person overrides to flag_evaluations, without consuming them.

    A merge leaves flag_evaluations rows on the person it absorbed until a rewrite moves them, and
    the weekly squash moves them only once a week. This one runs the same rewrite daily on that
    table alone, and stops before the delete: the squash still has to apply the overrides to the
    events tables, and it is the only job allowed to delete them afterwards.
    """
    prepared_snapshot_table = wait_for_snapshot_table_replication(populate_snapshot_table(create_snapshot_table()))
    prepared_dictionary = load_and_verify_snapshot_dictionary(create_snapshot_dictionary(prepared_snapshot_table))
    cleanup_snapshot_resources(run_flag_evaluations_person_id_update_mutations(prepared_dictionary))


@dagster.job(tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def cleanup_orphaned_person_overrides_snapshot():
    """
    Cleans up overrides snapshot resources after an irrecoverable job failure. This should only be run manually when the
    resources are guaranteed to no longer be in use (i.e. no mutations are in progress, and the specified job is no
    longer running and will not be retried.)

    Typically, these resources are automatically cleaned up after the job successfully completes. However, there are
    cases in which the job can fail and leave orphaned resources dangling around that can no longer be used and need to
    be manually removed from the cluster. This job can be used to perform the cleanup of those resources.
    """
    dictionary = get_existing_dictionary_for_run_id()
    cleanup_snapshot_resources(dictionary)


squash_schedule = dagster.ScheduleDefinition(
    job=squash_person_overrides,
    cron_schedule=settings.SQUASH_PERSON_OVERRIDES_SCHEDULE,
    execution_timezone="UTC",
    name="squash_person_overrides_schedule",
    # mutation waits can span hours, so allow more transient failures per host before failing the
    # weekly run (downstream deletes only trigger on success)
    run_config={"resources": {"cluster": {"config": {"retry_max_attempts": 20}}}},
)


@dagster.schedule(
    job=rewrite_flag_evaluations_person_id,
    cron_schedule=settings.FLAG_EVALUATIONS_PERSON_ID_REWRITE_SCHEDULE,
    execution_timezone="UTC",
    name="flag_evaluations_person_id_rewrite_schedule",
)
def flag_evaluations_person_id_rewrite_schedule(context: dagster.ScheduleEvaluationContext) -> dagster.RunRequest:
    """Run the rewrite against the overrides written before this tick.

    The snapshot timestamp comes from the tick rather than from the config default, which is a
    literal evaluated when the module is imported. A daily job that read it would snapshot the same
    window on every run for as long as the code server stays up, and so would never see a merge
    recorded after that import.
    """
    snapshot_timestamp = context.scheduled_execution_time - datetime.timedelta(days=SNAPSHOT_LAG_DAYS)
    return dagster.RunRequest(
        run_config={
            "ops": {
                populate_snapshot_table.name: {
                    "config": {"timestamp": snapshot_timestamp.strftime("%Y-%m-%d %H:%M:%S")}
                }
            },
            # Same allowance as the squash: a mutation wait can span hours and a transient host
            # failure should not fail the run.
            "resources": {"cluster": {"config": {"retry_max_attempts": 20}}},
        }
    )
