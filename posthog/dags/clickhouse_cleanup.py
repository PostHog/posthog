"""Weekly ClickHouse cleanup sweeps: deleted cohort memberships, then deleted persons.

ClickHouse cannot cheaply delete individual rows, so deletions are marked and swept later.
Both sweeps issue cluster-wide mutations, and running those at the same time overloads the
cluster, so the ops below are chained on each other's output to force them into sequence.
"""

import time
from dataclasses import dataclass
from functools import partial

from django.conf import settings

import dagster
import pydantic
from clickhouse_driver.client import Client

from posthog.clickhouse.cleanup_snapshots import CLEANUP_DELETED_PERSONS_TABLE
from posthog.clickhouse.client.connection import ClickHouseUser, get_clickhouse_creds
from posthog.clickhouse.cluster import (
    ClickhouseCluster,
    LightweightDeleteMutationRunner,
    MutationNotFound,
    NodeRole,
    RetryPolicy,
)
from posthog.dags.common import JobOwners
from posthog.models.async_deletion.delete_cohorts import sweep_cohort_deletions
from posthog.models.person.sql import PERSONS_TABLE


class CleanupConfig(dagster.Config):
    dry_run: bool = pydantic.Field(
        default=True,
        description="Build the snapshot and report what would be removed, without deleting anything.",
    )
    cleanup: bool = pydantic.Field(
        default=True,
        description="Drop the dictionary and clear this run's snapshot rows when the run finishes.",
    )
    shards: int = pydantic.Field(default=16, description="Dictionary SHARDS, which parallelize loading.")
    max_execution_time: int = pydantic.Field(default=0, description="Dictionary load timeout, 0 for no limit.")
    max_memory_usage: int = pydantic.Field(default=0, description="Dictionary load memory cap, 0 for no limit.")
    dictionary_load_timeout: int = pydantic.Field(
        default=600,
        description="How long to wait for a dictionary to finish loading on a host before failing the run.",
    )


@dataclass(frozen=True, kw_only=True)
class CleanupRun:
    """Every per-run asset, threaded through the ops so they execute in sequence.

    Settings that outlive the first op travel here rather than being read from config by each op,
    so they are set in one place. Declaring dry_run on every op would let a launch set it on one
    and miss another, and half a sweep is worse than none.
    """

    persons: "DeletedPersonsTable"
    dry_run: bool
    dictionary_load_timeout: int

    @property
    def persons_dictionary(self) -> "DeletedPersonsDictionary":
        return DeletedPersonsDictionary(source=self.persons)


@dataclass(frozen=True)
class DeletedPersonsTable:
    """One run's slice of the persons whose latest ClickHouse version is deleted.

    The sweep removes those rows, which destroys the tombstones the set was derived from, so
    the set is captured here first and every later step reads it from here rather than
    recomputing it.

    Every run writes into the same persisted table and reads back its own rows by run id.
    Creating and dropping a replicated table per run instead would churn DDL across every node
    once a week, and a run's rows expire on their own through the table's TTL.
    """

    run_id: str

    @property
    def table_name(self) -> str:
        return CLEANUP_DELETED_PERSONS_TABLE

    @property
    def qualified_name(self) -> str:
        return f"{settings.CLICKHOUSE_DATABASE}.{self.table_name}"

    def populate(self, client: Client) -> None:
        # A person can be soft-deleted and later revived by a higher version, so membership is
        # decided by the latest version rather than by any version having is_deleted set. The
        # inner IN narrows the aggregation to persons with at least one deleted version.
        client.execute(
            f"""
            INSERT INTO {self.qualified_name} (run_id, team_id, person_id, max_version)
            SELECT %(run_id)s, team_id, id, max(version)
            FROM {PERSONS_TABLE}
            WHERE (team_id, id) IN (SELECT team_id, id FROM {PERSONS_TABLE} WHERE is_deleted > 0)
            GROUP BY team_id, id
            HAVING argMax(is_deleted, version) > 0
            """,
            {"run_id": self.run_id},
        )

    def count(self, client: Client) -> int:
        [[count]] = client.execute(
            f"SELECT count() FROM {self.qualified_name} WHERE run_id = %(run_id)s",
            {"run_id": self.run_id},
        )
        return count

    def drop_run_partition(self, client: Client) -> None:
        # The table is partitioned by run_id, so clearing a run is a metadata-only partition drop
        # rather than a mutation that rewrites every part. A missing partition is a no-op.
        client.execute(
            f"ALTER TABLE {self.qualified_name} DROP PARTITION %(run_id)s",
            {"run_id": self.run_id},
        )


@dataclass(frozen=True)
class DeletedPersonsDictionary:
    source: DeletedPersonsTable

    @property
    def name(self) -> str:
        # Runs share the table, so the run id has to live on the dictionary instead for two runs
        # not to fight over one name.
        return f"{self.source.table_name}_{self.source.run_id}_dictionary"

    @property
    def qualified_name(self) -> str:
        return f"{settings.CLICKHOUSE_DATABASE}.{self.name}"

    @property
    def query(self) -> str:
        return (
            f"SELECT team_id, person_id, max_version FROM {self.source.qualified_name}"
            f" WHERE run_id = '{self.source.run_id}'"
        )

    def create(self, client: Client, shards: int, max_execution_time: int, max_memory_usage: int) -> None:
        # The source reads as the low-privilege dict_reader user, which falls back to the default
        # user's credentials where dict_reader is not provisioned. Credentials are query parameters
        # so they stay out of the traced statement.
        creds = get_clickhouse_creds(ClickHouseUser.DICT_READER)
        client.execute(
            f"""
            CREATE DICTIONARY IF NOT EXISTS {self.qualified_name} (
                team_id Int64,
                person_id UUID,
                max_version UInt64
            )
            PRIMARY KEY team_id, person_id
            SOURCE(CLICKHOUSE(DB %(database)s USER %(user)s PASSWORD %(password)s QUERY %(query)s))
            LAYOUT(COMPLEX_KEY_HASHED(SHARDS {shards}))
            LIFETIME(0)
            SETTINGS(max_execution_time={max_execution_time}, max_memory_usage={max_memory_usage})
            """,
            {
                "database": settings.CLICKHOUSE_DATABASE,
                "user": creds.user,
                "password": creds.password,
                "query": self.query,
            },
        )

    def drop(self, client: Client) -> None:
        client.execute(f"DROP DICTIONARY IF EXISTS {self.qualified_name} SYNC")

    def is_loaded(self, client: Client) -> bool:
        results = client.execute(
            "SELECT status, last_exception FROM system.dictionaries WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": self.name},
        )
        if not results:
            raise Exception(f"{self.qualified_name} does not exist")
        [[status, last_exception]] = results
        if status == "LOADED":
            return True
        if status in {"LOADING", "FAILED_AND_RELOADING", "LOADED_AND_RELOADING"}:
            return False
        if status == "FAILED":
            raise Exception(f"{self.qualified_name} failed to load: {last_exception}")
        raise Exception(f"{self.qualified_name} in unexpected status: {status}")

    def load(self, client: Client, timeout_seconds: int) -> int:
        client.execute(f"SYSTEM RELOAD DICTIONARY {self.qualified_name}")

        # The reload is asynchronous, so the mutation would read a half-populated dictionary
        # without this wait. A dictionary wedged in LOADING would otherwise hold the run open
        # forever, and a weekly job nobody is watching is exactly where that goes unnoticed.
        deadline = time.monotonic() + timeout_seconds
        while not self.is_loaded(client):
            if time.monotonic() > deadline:
                raise Exception(f"{self.qualified_name} still not loaded after {timeout_seconds}s")
            time.sleep(5.0)

        return self.checksum(client)

    def checksum(self, client: Client) -> int:
        # XOR is order independent, so hosts that hold the same keys agree regardless of read order.
        [[checksum]] = client.execute(f"SELECT groupBitXor(cityHash64(team_id, person_id)) FROM {self.qualified_name}")
        return checksum


@dagster.op
def clear_removed_cohort_data(
    context: dagster.OpExecutionContext,
    config: CleanupConfig,
) -> CleanupRun:
    """Remove cohort membership rows for cohorts that were deleted or recalculated.

    Runs ahead of the person sweep rather than after it. The two cannot overlap, and the person
    mutation can run for hours, so putting it first would leave cohort rows unswept whenever it
    ran long or failed. Going first also keeps the person snapshot as close to its own delete as
    possible, which is what bounds how many persons can revive mid-run.
    """
    run = CleanupRun(
        persons=DeletedPersonsTable(run_id=context.run_id.replace("-", "_")),
        dry_run=config.dry_run,
        dictionary_load_timeout=config.dictionary_load_timeout,
    )
    context.add_output_metadata({"dry_run": dagster.MetadataValue.bool(run.dry_run)})

    if run.dry_run:
        context.log.info("dry run: skipping the cohort sweep")
        return run

    failed = sweep_cohort_deletions()
    context.add_output_metadata({"failed_passes": dagster.MetadataValue.text(", ".join(failed) or "none")})
    return run


@dagster.op
def snapshot_deleted_persons(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    run: CleanupRun,
) -> CleanupRun:
    """Capture the persons whose latest version is deleted, tagged with this run's id."""
    table = run.persons

    cluster.any_host_by_role(table.populate, NodeRole.DATA).result()

    # The insert lands on one host, but every host reads this table when the dictionary loads.
    def sync_replica(client: Client) -> None:
        client.execute(f"SYSTEM SYNC REPLICA {table.qualified_name} STRICT")

    cluster.map_all_hosts(sync_replica).result()

    count = cluster.any_host_by_role(table.count, NodeRole.DATA).result()
    context.add_output_metadata(
        {
            "deleted_persons": dagster.MetadataValue.int(count),
            "table_name": dagster.MetadataValue.text(table.table_name),
        }
    )
    return run


@dagster.op
def build_deleted_persons_dictionary(
    config: CleanupConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    run: CleanupRun,
) -> CleanupRun:
    """Create the dictionary the delete predicate probes, on every host."""
    cluster.map_all_hosts(
        partial(
            run.persons_dictionary.create,
            shards=config.shards,
            max_execution_time=config.max_execution_time,
            max_memory_usage=config.max_memory_usage,
        )
    ).result()
    return run


@dagster.op
def load_and_verify_deleted_persons_dictionary(
    cluster: dagster.ResourceParam[ClickhouseCluster],
    run: CleanupRun,
) -> CleanupRun:
    """Load the dictionary on all hosts and confirm they hold identical keys."""
    checksums = cluster.map_all_hosts(
        partial(run.persons_dictionary.load, timeout_seconds=run.dictionary_load_timeout),
        concurrency=1,
    ).result()
    assert len(set(checksums.values())) == 1
    return run


@dagster.op
def delete_persons(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    run: CleanupRun,
) -> CleanupRun:
    """Remove the snapshotted persons from the ClickHouse person table.

    Bounded by the version the snapshot observed, so a person recreated after the snapshot keeps
    the rows this run never saw. Without the bound, a client recapturing a deleted distinct id
    mid-run would have that new person state swept away.
    """
    if run.dry_run:
        context.log.info("dry run: skipping the delete from %s", PERSONS_TABLE)
        return run

    dictionary = run.persons_dictionary.qualified_name
    runner = LightweightDeleteMutationRunner(
        table=PERSONS_TABLE,
        predicate=(
            f"isNotNull(dictGetOrNull({dictionary!r}, 'max_version', (team_id, id)) as snapshot_max)"
            " AND version <= snapshot_max"
        ),
    )

    # person is replicated and not sharded, so a mutation started on one host reaches all of them.
    mutation = cluster.any_host(runner).result()
    # The mutation entry replicates through Keeper, so a lagged replica can briefly not know it
    # and raise MutationNotFound; retry the wait like MutationRunner.run_on_shards does.
    retry_lagged_replicas = RetryPolicy(max_attempts=3, delay=10.0, exceptions=(MutationNotFound,))
    cluster.map_all_hosts(retry_lagged_replicas(mutation.wait)).result()

    return run


@dagster.op
def drop_snapshot_assets(
    context: dagster.OpExecutionContext,
    config: CleanupConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    run: CleanupRun,
) -> None:
    """Drop this run's dictionary and clear the rows it read."""
    dictionary = run.persons_dictionary

    if not config.cleanup:
        context.log.info("cleanup disabled, leaving %s in place", dictionary.qualified_name)
        return

    # The dictionary reads from the table, so it has to go first.
    cluster.map_all_hosts(dictionary.drop).result()
    # The TTL would reap these anyway. Clearing them now keeps the shared table small enough that
    # a run's own rows stay cheap to read.
    cluster.any_host_by_role(run.persons.drop_run_partition, NodeRole.DATA).result()


@dagster.failure_hook(required_resource_keys={"cluster"})
def drop_assets_on_failure(context: dagster.HookContext) -> None:
    """Drop this run's dictionary when an op fails.

    Dagster skips downstream ops after a failure, so drop_snapshot_assets never runs and the
    dictionary would survive on the cluster and accumulate across failures. The name comes from
    the run id alone, so this needs nothing from the failed op.

    This ignores the cleanup flag on purpose. A stranded dictionary holds its whole key set in
    memory on every host, which costs more than the ability to inspect it after a failure.

    The failed run's rows are left behind deliberately. They cost far less than a dictionary and
    the table's TTL reaps them, so a failed sweep stays inspectable in the meantime.
    """
    run_id = context.run_id.replace("-", "_")
    name = f"{settings.CLICKHOUSE_DATABASE}.{CLEANUP_DELETED_PERSONS_TABLE}_{run_id}_dictionary"
    cluster = context.resources.cluster

    cluster.map_all_hosts(lambda client: client.execute(f"DROP DICTIONARY IF EXISTS {name} SYNC")).result()


@dagster.job(hooks={drop_assets_on_failure}, tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def clickhouse_deletion_sweep_job():
    """Sweep deleted cohort memberships out of ClickHouse, then deleted persons."""
    # Each op takes the previous op's output, which is what keeps the two sweeps in sequence.
    run = snapshot_deleted_persons(clear_removed_cohort_data())
    drop_snapshot_assets(
        delete_persons(load_and_verify_deleted_persons_dictionary(build_deleted_persons_dictionary(run)))
    )
