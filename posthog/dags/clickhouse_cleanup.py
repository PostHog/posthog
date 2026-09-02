"""Weekly ClickHouse cleanup sweeps: deleted cohort memberships, then deleted persons and the
distinct ids that belonged to them.

ClickHouse cannot cheaply delete individual rows, so deletions are marked and swept later. Every
sweep issues cluster-wide mutations, and running those at the same time overloads the cluster, so
the ops below are chained on each other's output to force them into sequence.

The person sweep destroys the tombstones its own worklist is derived from, so the run freezes that
worklist into a persisted snapshot table first, scoped by run id. Everything downstream, including
the Postgres handoff, reads the snapshot rather than recomputing it.
"""

import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from math import ceil

from django.conf import settings

import dagster
import psycopg2
import pydantic
from clickhouse_driver.client import Client
from prometheus_client import Counter
from psycopg2.extras import execute_values

from posthog.clickhouse.cleanup_snapshots import (
    CLEANUP_DELETED_PERSONS_TABLE,
    CLEANUP_ORPHANED_DISTINCT_IDS_TABLE,
    CLEANUP_REVIVED_DISTINCT_IDS_TABLE,
    CLEANUP_REVIVED_PERSONS_TABLE,
    CLEANUP_SNAPSHOT_TABLES,
)
from posthog.clickhouse.client.connection import ClickHouseCredentials, ClickHouseUser, get_clickhouse_creds
from posthog.clickhouse.cluster import ClickhouseCluster, LightweightDeleteMutationRunner, MutationWaiter, NodeRole
from posthog.clickhouse.custom_metrics import MetricsClient
from posthog.dags.common import JobOwners
from posthog.dags.common.common import settings_with_log_comment
from posthog.dags.common.dictionaries import Dictionary
from posthog.dags.common.staged_dictionary import (
    StagedDictionary,
    create_on_every_cluster,
    load_and_verify_on_every_cluster,
)
from posthog.dataclasses import frozen
from posthog.models.async_deletion.delete_cohorts import sweep_cohort_deletions
from posthog.models.person.sql import PERSON_DISTINCT_ID2_TABLE, PERSONS_TABLE

logger = dagster.get_dagster_logger(__name__)

REVIVED_PERSON_COUNTER = Counter(
    "posthog_clickhouse_cleanup_revived_persons_total",
    "Persons that came back to life between the snapshot and the sweep, and were excluded",
)

REVIVED_DISTINCT_ID_COUNTER = Counter(
    "posthog_clickhouse_cleanup_revived_distinct_ids_total",
    "Distinct id mappings that came back between the snapshot and the sweep, and were excluded",
)

PG_CLEANUP_QUEUE_TABLE = "person_pg_cleanup_queue"

# How many queued persons travel per ClickHouse read and per Postgres upsert transaction. Bounds
# the op's memory to one page however large the snapshot is.
PERSIST_PAGE_SIZE = 50_000

# Each delete runs as one pair of ordered mutations per contiguous team-id range. Batches run in
# sequence, never in parallel, and ranges do not reduce what a mutation reads or rewrites: merged
# parts span nearly the whole team-id space, so every extra batch re-reads most parts and
# re-rewrites their delete masks. Total mutation cost is therefore roughly N times the single
# batch cost. What batching buys is a bound on one mutation's wall time under the wait deadline,
# and per-range progress in the logs. The default is 1 because those rarely justify the cost;
# raise team_batches together with max_persons when draining a large backlog in checkpoints.
DEFAULT_TEAM_BATCHES = 1


class CleanupConfig(dagster.Config):
    """Read once, by the first op, and carried to every later op on CleanupRun.

    Setting any of these on another op's config has no effect.
    """

    dry_run: bool = pydantic.Field(
        default=True,
        description="Build the snapshot and report what would be removed, without deleting anything.",
    )
    cleanup: bool = pydantic.Field(
        default=True,
        description="Drop the dictionaries and clear this run's snapshot rows when the run finishes. "
        "False keeps them only until the next run's janitor reaps them.",
    )
    team_batches: int = pydantic.Field(
        default=DEFAULT_TEAM_BATCHES,
        description="How many contiguous team ranges to split each delete into.",
    )
    shards: int = pydantic.Field(default=16, description="Dictionary SHARDS, which parallelize loading.")
    max_execution_time: int = pydantic.Field(default=0, description="Dictionary load timeout, 0 for no limit.")
    max_memory_usage: int = pydantic.Field(default=0, description="Dictionary load memory cap, 0 for no limit.")
    dictionary_load_timeout: int = pydantic.Field(
        default=600,
        description="How long to wait for a dictionary to finish loading on a host before failing the run.",
    )
    mutation_stall_timeout: int = pydantic.Field(
        default=1800,
        description="Fail a delete batch when attempts keep failing and no part completes for this many seconds.",
    )
    mutation_wait_deadline: int = pydantic.Field(
        default=86400,
        description="Fail a delete batch that has not finished after this many seconds, even when it is healthy. "
        "A mutation blocked behind another table-sized mutation would otherwise hold the run open forever.",
    )
    max_persons: int = pydantic.Field(
        default=0,
        description="Snapshot at most this many deleted persons, 0 for all of them. A capped run deletes a slice "
        "and the next run picks up the rest, because the worklist derives from the tombstones that remain.",
    )
    min_team_id: int = pydantic.Field(default=0, description="Only sweep persons with team_id >= this, 0 to disable.")
    max_team_id: int = pydantic.Field(default=0, description="Only sweep persons with team_id <= this, 0 to disable.")


@dataclass(frozen=True)
class SnapshotTable:
    """One run's rows in a persisted worklist holding one stage of the sweep.

    Every run writes into the same table and reads back its own rows by run id. Creating and
    dropping a replicated table per run instead would churn DDL across every node once a week.
    `run_id` leads the sort key, so a run reads only its own rows through the primary index, and
    a successful run clears them when it finishes.
    """

    run_id: str

    @property
    def table_name(self) -> str:
        raise NotImplementedError

    @property
    def keys(self) -> str:
        """The columns that identify a row within a run."""
        raise NotImplementedError

    @property
    def dictionary_types(self) -> str:
        """The column list a dictionary over this table declares."""
        raise NotImplementedError

    @property
    def qualified_name(self) -> str:
        return f"{settings.CLICKHOUSE_DATABASE}.{self.table_name}"

    @property
    def run_keys_query(self) -> str:
        """This run's keys, for embedding in an IN or NOT IN clause.

        The run id is interpolated rather than passed as a parameter because these fragments end
        up inside dictionary source queries and mutation commands, neither of which carries
        parameters. It is a Dagster run id with the dashes replaced, so there is nothing to quote.
        """
        return f"SELECT {self.keys} FROM {self.qualified_name} WHERE run_id = '{self.run_id}'"

    def count(self, client: Client) -> int:
        [[count]] = client.execute(
            f"SELECT count() FROM {self.qualified_name} WHERE run_id = %(run_id)s",
            {"run_id": self.run_id},
        )
        return count

    def team_ids(self, client: Client) -> list[int]:
        rows = client.execute(
            f"SELECT DISTINCT team_id FROM {self.qualified_name} WHERE run_id = %(run_id)s ORDER BY team_id",
            {"run_id": self.run_id},
        )
        return [row[0] for row in rows]

    def distinct_key_count(self, client: Client) -> int:
        # Deduplicated, so the number is stable whether or not a merge has collapsed the
        # duplicate rows a retried populate leaves behind.
        [[count]] = client.execute(
            f"SELECT count() FROM (SELECT {self.keys} FROM {self.qualified_name}"
            f" WHERE run_id = %(run_id)s GROUP BY {self.keys})",
            {"run_id": self.run_id},
        )
        return count

    def sync_replica(self, client: Client) -> None:
        client.execute(f"SYSTEM SYNC REPLICA {self.qualified_name} STRICT")

    def drop_run_partition(self, client: Client) -> None:
        # The table is partitioned by run_id, so clearing a run is a metadata-only partition drop
        # rather than a mutation that rewrites every part. A missing partition is a no-op.
        client.execute(
            f"ALTER TABLE {self.qualified_name} DROP PARTITION %(run_id)s",
            {"run_id": self.run_id},
        )


@dataclass(frozen=True)
class DeletedPersonsTable(SnapshotTable):
    """Persons whose latest ClickHouse version is deleted."""

    table_name = CLEANUP_DELETED_PERSONS_TABLE
    keys = "team_id, person_id"
    dictionary_types = "team_id Int64, person_id UUID, max_version UInt64"

    def populate(
        self,
        client: Client,
        settings: Mapping[str, int] | None = None,
        min_team_id: int = 0,
        max_team_id: int = 0,
        max_persons: int = 0,
    ) -> None:
        # A person can be soft-deleted and later revived by a higher version, so membership is
        # decided by the latest version rather than by any version having is_deleted set. The
        # inner IN narrows the aggregation to persons with at least one deleted version.
        # The team filter and the LIMIT bound what one run takes on; whatever they exclude keeps
        # its tombstones, so the next run picks it up. team_id leads the sort key, which is what
        # lets the range prune the scan rather than only filter it.
        team_filter = ""
        if min_team_id:
            team_filter += f" AND team_id >= {int(min_team_id)}"
        if max_team_id:
            team_filter += f" AND team_id <= {int(max_team_id)}"
        cap = f" ORDER BY team_id, id LIMIT {int(max_persons)}" if max_persons else ""
        client.execute(
            f"""
            INSERT INTO {self.qualified_name} (run_id, team_id, person_id, max_version)
            SELECT %(run_id)s, team_id, id, max(version)
            FROM {PERSONS_TABLE}
            WHERE (team_id, id) IN (SELECT team_id, id FROM {PERSONS_TABLE} WHERE is_deleted > 0{team_filter}){team_filter}
            GROUP BY team_id, id
            HAVING argMax(is_deleted, version) > 0{cap}
            """,
            {"run_id": self.run_id},
            settings=settings,
        )


@dataclass(frozen=True)
class RevivedPersonsTable(SnapshotTable):
    """Snapshotted persons that came back to life while the run was in flight.

    Every dictionary below reads its source through an anti-join against this table, so recording
    a revival here is what excludes it. That keeps the checkpoints free of mutations on the
    snapshot tables, which would be far slower than an insert.
    """

    table_name = CLEANUP_REVIVED_PERSONS_TABLE
    keys = "team_id, person_id"
    dictionary_types = "team_id Int64, person_id UUID"

    def populate(self, client: Client, persons: DeletedPersonsTable, settings: Mapping[str, int] | None = None) -> int:
        # Later checkpoints re-run this, so already-recorded revivals are excluded rather than
        # inserted again. Counting this run's rows is what reports how many are newly revived.
        client.execute(
            f"""
            INSERT INTO {self.qualified_name} (run_id, team_id, person_id)
            SELECT %(run_id)s, team_id, id
            FROM {PERSONS_TABLE}
            WHERE (team_id, id) IN ({persons.run_keys_query})
              AND (team_id, id) NOT IN ({self.run_keys_query})
            GROUP BY team_id, id
            HAVING argMax(is_deleted, version) = 0
            """,
            {"run_id": self.run_id},
            settings=settings,
        )
        return self.count(client)


@dataclass(frozen=True)
class OrphanedDistinctIdsTable(SnapshotTable):
    """Distinct ids to remove, with the reason each one qualified.

    own_tombstone records why a key is here. The exclusion at each checkpoint is re-derived from
    live data in RevivedDistinctIdsTable rather than from this column, because both the tombstone
    and the owner can change while the run is in flight.
    """

    table_name = CLEANUP_ORPHANED_DISTINCT_IDS_TABLE
    keys = "team_id, distinct_id"
    dictionary_types = "team_id Int64, distinct_id String, max_version Int64"

    def populate(
        self, client: Client, persons_dictionary: "SnapshotDictionary", settings: Mapping[str, int] | None = None
    ) -> None:
        # person_distinct_id2 is keyed on (team_id, distinct_id) with person_id as a value, so a
        # distinct id can be repointed over time. Deleting rows that merely match a deleted
        # person_id can strip the newest row and resurrect an older mapping underneath it, so the
        # current owner is resolved with argMax and every version of a qualifying key is removed.
        client.execute(
            f"""
            INSERT INTO {self.qualified_name} (run_id, team_id, distinct_id, person_id, own_tombstone, max_version)
            SELECT
                %(run_id)s,
                team_id,
                distinct_id,
                argMax(person_id, version) AS person_id,
                argMax(is_deleted, version) > 0 AS own_tombstone,
                max(version) AS max_version
            FROM {PERSON_DISTINCT_ID2_TABLE}
            WHERE (team_id, distinct_id) IN (
                SELECT team_id, distinct_id
                FROM {PERSON_DISTINCT_ID2_TABLE}
                WHERE is_deleted > 0 OR dictHas('{persons_dictionary.qualified_name}', (team_id, person_id))
            )
            GROUP BY team_id, distinct_id
            HAVING own_tombstone OR dictHas('{persons_dictionary.qualified_name}', (team_id, person_id))
            """,
            {"run_id": self.run_id},
            settings=settings,
        )


@dataclass(frozen=True)
class RevivedDistinctIdsTable(SnapshotTable):
    """Snapshotted distinct ids that no longer qualify for deletion.

    A mapping can come back the same way a person can: ingestion re-captures a tombstoned
    distinct id, or reset_deleted_person_distinct_ids republishes it at a higher version. The
    snapshot froze the reason each key qualified, so without this the delete would strip every
    version of a key that is live again, including the new row.
    """

    table_name = CLEANUP_REVIVED_DISTINCT_IDS_TABLE
    keys = "team_id, distinct_id"
    dictionary_types = "team_id Int64, distinct_id String"

    def populate(
        self,
        client: Client,
        orphaned: OrphanedDistinctIdsTable,
        persons: DeletedPersonsTable,
        revived: RevivedPersonsTable,
        settings: Mapping[str, int] | None = None,
    ) -> int:
        # A key stops qualifying once its latest version is live AND its current owner is not a
        # person this run is still deleting. Both arms of the original predicate have to fail.
        client.execute(
            f"""
            INSERT INTO {self.qualified_name} (run_id, team_id, distinct_id)
            SELECT %(run_id)s, team_id, distinct_id
            FROM {PERSON_DISTINCT_ID2_TABLE}
            WHERE (team_id, distinct_id) IN ({orphaned.run_keys_query})
              AND (team_id, distinct_id) NOT IN ({self.run_keys_query})
            GROUP BY team_id, distinct_id
            HAVING argMax(is_deleted, version) = 0
               AND (team_id, argMax(person_id, version)) NOT IN (
                   SELECT team_id, person_id FROM {persons.qualified_name}
                   WHERE run_id = '{persons.run_id}'
                     AND (team_id, person_id) NOT IN ({revived.run_keys_query})
               )
            """,
            {"run_id": self.run_id},
            settings=settings,
        )
        return self.count(client)


@frozen
class SnapshotDictionary(Dictionary):
    """A cluster-wide dictionary over one run's rows in a worklist, minus anything since revived.

    The inherited checksum hashes every declared column, which here includes max_version: the
    delete mutation reads it from each host's local dictionary, so hosts agreeing on keys but
    not on the version bound would delete different version sets per replica and diverge the
    table.
    """

    source: SnapshotTable
    # Keys recorded here are anti-joined out of the dictionary, which is how a checkpoint
    # excludes something without mutating the worklist it came from.
    excluded: SnapshotTable

    @property
    def key_columns(self) -> str:
        return self.source.keys

    @property
    def name(self) -> str:
        # Runs share the tables, so the run id has to live on the dictionary instead for two runs
        # not to fight over one name.
        return f"{self.source.table_name}_{self.source.run_id}_dictionary"

    @property
    def schema(self) -> str:
        return self.source.dictionary_types

    @property
    def primary_key(self) -> str:
        return self.key_columns

    @property
    def query(self) -> str:
        # Aggregated because a retried populate leaves duplicate key rows until a merge collapses
        # them, and an unaggregated read would hand the dictionary an arbitrary one. max() picks
        # the newest bound, matching the row the sub-second version column keeps at merge time.
        return f"""
            SELECT {self.key_columns}, max(max_version) AS max_version
            FROM {self.source.qualified_name}
            WHERE run_id = '{self.source.run_id}'
              AND ({self.key_columns}) NOT IN ({self.excluded.run_keys_query})
            GROUP BY {self.key_columns}
        """

    @property
    def credentials(self) -> ClickHouseCredentials:
        # The source reads as the low-privilege dict_reader user, which falls back to the default
        # user's credentials where dict_reader is not provisioned.
        return get_clickhouse_creds(ClickHouseUser.DICT_READER)

    def staged(self) -> StagedDictionary:
        # A staged copy is a static object. The revival checkpoints exclude keys by reloading this
        # dictionary so its source query re-runs against the live exclusion table, and a reload
        # of a staged copy on another cluster would keep every revived key in the delete set.
        # The sweep only mutates replicated tables on the cluster in hand, so it never needs one.
        raise NotImplementedError(
            f"{self.name} cannot be staged: its contents change during the run, and a staged copy would not"
        )


@dataclass(frozen=True, kw_only=True)
class CleanupRun:
    """Every per-run asset and setting, threaded through the ops so they execute in sequence.

    Settings travel here rather than being read from config by each op, so a launch sets them in
    one place: the first op's config. Declaring them per op would let a launch set one on some
    ops and miss others, and a sweep whose halves disagree on dry_run or batching is worse than
    none.
    """

    persons: DeletedPersonsTable
    revived: RevivedPersonsTable
    orphaned: OrphanedDistinctIdsTable
    revived_distinct_ids: RevivedDistinctIdsTable
    dry_run: bool
    cleanup: bool
    team_batches: int
    shards: int
    max_execution_time: int
    max_memory_usage: int
    dictionary_load_timeout: int
    mutation_stall_timeout: int
    mutation_wait_deadline: int
    max_persons: int
    min_team_id: int
    max_team_id: int
    distinct_ids_deleted_at: datetime | None = None
    # Distinct key counts recorded when each snapshot was taken. The deletes assert against them,
    # so a snapshot the 14-day TTL reaped mid-run fails the run instead of under-deleting silently.
    persons_count: int = 0
    orphaned_count: int = 0

    @classmethod
    def for_run(cls, run_id: str, config: CleanupConfig) -> "CleanupRun":
        # Dictionary names embed the run id, and a dash is not valid in an identifier.
        scoped = run_id.replace("-", "_")
        return cls(
            persons=DeletedPersonsTable(run_id=scoped),
            revived=RevivedPersonsTable(run_id=scoped),
            orphaned=OrphanedDistinctIdsTable(run_id=scoped),
            revived_distinct_ids=RevivedDistinctIdsTable(run_id=scoped),
            dry_run=config.dry_run,
            cleanup=config.cleanup,
            team_batches=config.team_batches,
            shards=config.shards,
            max_execution_time=config.max_execution_time,
            max_memory_usage=config.max_memory_usage,
            dictionary_load_timeout=config.dictionary_load_timeout,
            mutation_stall_timeout=config.mutation_stall_timeout,
            mutation_wait_deadline=config.mutation_wait_deadline,
            max_persons=config.max_persons,
            min_team_id=config.min_team_id,
            max_team_id=config.max_team_id,
        )

    @property
    def query_settings(self) -> dict[str, int]:
        """Caps for the snapshot INSERT..SELECTs, which scan person and person_distinct_id2 whole.

        Without these the populates run unbounded; the dictionary loads already honor the same
        two config fields, so one launch config bounds every heavy read in the run.
        """
        return {"max_execution_time": self.max_execution_time, "max_memory_usage": self.max_memory_usage}

    @property
    def all_tables(self) -> tuple[SnapshotTable, ...]:
        return (self.persons, self.revived, self.orphaned, self.revived_distinct_ids)

    @property
    def persons_dictionary(self) -> SnapshotDictionary:
        return SnapshotDictionary(source=self.persons, excluded=self.revived, load_timeout=self.dictionary_load_timeout)

    @property
    def orphaned_dictionary(self) -> SnapshotDictionary:
        return SnapshotDictionary(
            source=self.orphaned, excluded=self.revived_distinct_ids, load_timeout=self.dictionary_load_timeout
        )


def _create_dictionary(
    context: dagster.OpExecutionContext,
    cluster: ClickhouseCluster,
    dictionary: SnapshotDictionary,
    run: CleanupRun,
) -> SnapshotDictionary:
    # Only the cluster in hand: the sweep's tables are replicated there and nowhere else, and
    # SnapshotDictionary refuses staging, so a second cluster would fail here rather than diverge.
    create_on_every_cluster(
        context,
        [cluster],
        dictionary,
        shards=run.shards,
        max_execution_time=run.max_execution_time,
        max_memory_usage=run.max_memory_usage,
    )
    load_and_verify_on_every_cluster([cluster], dictionary)
    return dictionary


@dagster.op
def clear_removed_cohort_data(
    context: dagster.OpExecutionContext,
    config: CleanupConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> CleanupRun:
    """Remove cohort membership rows for cohorts that were deleted or recalculated.

    Runs ahead of the person sweep rather than after it. The sweeps cannot overlap, and the person
    path runs for hours, so putting it last would leave cohort rows unswept whenever that path ran
    long or failed. Going first also keeps the person snapshot as close to its own delete as
    possible, which is what bounds how many persons can revive mid-run.
    """
    run = CleanupRun.for_run(context.run_id, config)
    reaped = reap_stranded_run_assets(context, cluster)
    context.add_output_metadata(
        {
            "dry_run": dagster.MetadataValue.bool(run.dry_run),
            "stranded_runs_reaped": dagster.MetadataValue.int(reaped),
        }
    )

    if run.dry_run:
        context.log.info("dry run: skipping the cohort sweep")
        return run

    failed = sweep_cohort_deletions()
    context.add_output_metadata({"failed_passes": dagster.MetadataValue.text(", ".join(failed) or "none")})
    # The prometheus counters sweep_cohort_deletions increments die with this run's pod, so the
    # scrapeable record of a failed pass is the ClickHouse-backed counter.
    for name in failed:
        _emit(MetricsClient(cluster), "clickhouse_cleanup_cohort_sweep_failed_passes", {"pass": name})
    return run


@dagster.op
def snapshot_deleted_persons(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    run: CleanupRun,
) -> CleanupRun:
    """Capture the persons whose latest version is deleted, tagged with this run's id."""
    started = time.monotonic()
    cluster.any_host_by_role(
        partial(
            run.persons.populate,
            settings=run.query_settings,
            min_team_id=run.min_team_id,
            max_team_id=run.max_team_id,
            max_persons=run.max_persons,
        ),
        NodeRole.DATA,
    ).result()
    # The insert lands on one host, but every host reads this table when the dictionary loads.
    cluster.map_all_hosts(run.persons.sync_replica).result()

    count = cluster.any_host_by_role(run.persons.distinct_key_count, NodeRole.DATA).result()
    context.add_output_metadata(
        {
            "deleted_persons": dagster.MetadataValue.int(count),
            "snapshot_seconds": dagster.MetadataValue.float(round(time.monotonic() - started, 1)),
        }
    )
    return replace(run, persons_count=count)


@dagster.op
def snapshot_orphaned_distinct_ids(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    run: CleanupRun,
) -> CleanupRun:
    """Resolve which distinct ids belong to the snapshotted persons, or tombstoned themselves."""
    _create_dictionary(context, cluster, run.persons_dictionary, run)

    started = time.monotonic()
    cluster.any_host_by_role(
        partial(run.orphaned.populate, persons_dictionary=run.persons_dictionary, settings=run.query_settings),
        NodeRole.DATA,
    ).result()
    cluster.map_all_hosts(run.orphaned.sync_replica).result()
    snapshot_seconds = round(time.monotonic() - started, 1)
    _create_dictionary(context, cluster, run.orphaned_dictionary, run)

    count = cluster.any_host_by_role(run.orphaned.distinct_key_count, NodeRole.DATA).result()
    context.add_output_metadata(
        {
            "orphaned_distinct_ids": dagster.MetadataValue.int(count),
            "snapshot_seconds": dagster.MetadataValue.float(snapshot_seconds),
        }
    )
    return replace(run, orphaned_count=count)


def recheck_revived_persons(name: str) -> dagster.OpDefinition:
    """Build a checkpoint op that excludes any person revived since the snapshot.

    The checkpoints sit at phase boundaries rather than inside the mutation, because a mutation
    over an unpartitioned table runs long and re-checking mid-flight cannot retract work already
    applied. A person revived inside that window has already lost its distinct id rows;
    reset_deleted_person_distinct_ids and the sync_person_distinct_ids workflow republish them
    from Postgres.
    """

    @dagster.op(name=name)
    def checkpoint(
        context: dagster.OpExecutionContext,
        cluster: dagster.ResourceParam[ClickhouseCluster],
        run: CleanupRun,
    ) -> CleanupRun:
        persons_before = cluster.any_host_by_role(run.revived.count, NodeRole.DATA).result()
        persons_total = cluster.any_host_by_role(
            partial(run.revived.populate, persons=run.persons, settings=run.query_settings), NodeRole.DATA
        ).result()
        cluster.map_all_hosts(run.revived.sync_replica).result()

        # Runs second: which distinct ids still qualify depends on which persons are still deleted.
        ids_before = cluster.any_host_by_role(run.revived_distinct_ids.count, NodeRole.DATA).result()
        ids_total = cluster.any_host_by_role(
            partial(
                run.revived_distinct_ids.populate,
                orphaned=run.orphaned,
                persons=run.persons,
                revived=run.revived,
                settings=run.query_settings,
            ),
            NodeRole.DATA,
        ).result()
        cluster.map_all_hosts(run.revived_distinct_ids.sync_replica).result()

        revived_persons = persons_total - persons_before
        revived_ids = ids_total - ids_before
        context.add_output_metadata(
            {
                "revived_persons": dagster.MetadataValue.int(revived_persons),
                "revived_distinct_ids": dagster.MetadataValue.int(revived_ids),
            }
        )
        if not revived_persons and not revived_ids:
            return run

        # Reloading is what applies the exclusion, so it only happens when something came back.
        # Counted twice on purpose: the prometheus counters only surface if this pod is ever
        # scraped, while the ClickHouse-backed counters survive the run.
        REVIVED_PERSON_COUNTER.inc(revived_persons)
        REVIVED_DISTINCT_ID_COUNTER.inc(revived_ids)
        metrics = MetricsClient(cluster)
        if revived_persons:
            _emit(metrics, "clickhouse_cleanup_revived", {"kind": "persons"}, value=revived_persons)
        if revived_ids:
            _emit(metrics, "clickhouse_cleanup_revived", {"kind": "distinct_ids"}, value=revived_ids)
        context.log.warning(
            "%s persons and %s distinct ids came back during the run and are excluded from it",
            revived_persons,
            revived_ids,
        )
        for dictionary in (run.persons_dictionary, run.orphaned_dictionary):
            load_and_verify_on_every_cluster([cluster], dictionary)
        return run

    return checkpoint


def _emit(metrics: MetricsClient, name: str, labels: Mapping[str, str], value: float = 1.0) -> None:
    """Record a counter, never letting telemetry fail the sweep."""
    try:
        metrics.increment(name, labels=dict(labels), value=value).result()
    except Exception:
        logger.warning("failed to record %s", name, exc_info=True)


MUTATION_POLL_SECONDS = 15.0
MUTATION_VISIBILITY_TIMEOUT_SECONDS = 300.0


class MutationStalled(Exception):
    pass


@dataclass(frozen=True, kw_only=True)
class MutationStatus:
    """One host's view of a delete batch's mutations, read from its system.mutations."""

    done: bool
    visible: bool
    parts_to_do: int
    latest_fail_time: datetime | None
    latest_fail_reason: str
    server_now: datetime


class MutationProgress:
    """Decides when a polled mutation is stuck rather than merely slow or still retrying.

    ClickHouse retries a failed part mutation on its own, and system.mutations keeps the
    latest_fail_* columns populated from the newest failed attempt even after later attempts
    succeed, so a failure reason alone is not evidence the mutation is dying. A batch is declared
    stuck only when attempts are still failing while no part has completed for stall_timeout
    seconds. A batch that is slow without failing is left to run: that is a big part or a busy
    cluster, not a fault.

    A failure recorded before polling began is treated as history rather than evidence, because
    MutationRunner can re-attach to an existing mutation whose old attempts failed; only failures
    within one stall window of the first poll, or newer than the newest one already seen, count.
    """

    def __init__(
        self,
        stall_timeout: float,
        visibility_timeout: float = MUTATION_VISIBILITY_TIMEOUT_SECONDS,
        wait_deadline: float = 0.0,
    ) -> None:
        self.stall_timeout = stall_timeout
        self.visibility_timeout = visibility_timeout
        # A mutation can be healthy and still never finish, for example blocked behind another
        # table-sized mutation. The deadline turns that silent forever-run into a failure.
        self.wait_deadline = wait_deadline
        self._started_at: float | None = None
        self._last_progress_at: float = 0.0
        self._min_parts_to_do: int | None = None
        self._last_fail_time: datetime | None = None
        self._failed_since_progress = False

    def observe(self, statuses: Sequence[MutationStatus], now: float) -> None:
        """Digest one poll of every host, raising MutationStalled when the batch is stuck."""
        first = self._started_at is None
        if first:
            self._started_at = now
            self._last_progress_at = now
        assert self._started_at is not None

        if not all(status.visible for status in statuses):
            # The mutation entry replicates through Keeper, so a lagged replica can briefly not
            # know it yet; that only becomes a fault when it persists.
            if now - self._started_at > self.visibility_timeout:
                raise MutationStalled(f"not visible on every host after {self.visibility_timeout:.0f}s")
            return

        parts_to_do = sum(status.parts_to_do for status in statuses)
        if self._min_parts_to_do is None or parts_to_do < self._min_parts_to_do:
            self._min_parts_to_do = parts_to_do
            self._last_progress_at = now
            self._failed_since_progress = False

        newest_fail = max((s.latest_fail_time for s in statuses if s.latest_fail_time is not None), default=None)
        if first:
            self._last_fail_time = newest_fail
            if newest_fail is not None:
                freshness_horizon = max(s.server_now for s in statuses) - timedelta(seconds=self.stall_timeout)
                self._failed_since_progress = newest_fail > freshness_horizon
        elif newest_fail is not None and (self._last_fail_time is None or newest_fail > self._last_fail_time):
            self._last_fail_time = newest_fail
            self._failed_since_progress = True

        stalled_for = now - self._last_progress_at
        if self._failed_since_progress and stalled_for > self.stall_timeout:
            raise MutationStalled(f"attempts keep failing and no part completed in {stalled_for:.0f}s")

        if self.wait_deadline and now - self._started_at > self.wait_deadline:
            raise MutationStalled(f"not finished after {self.wait_deadline:.0f}s")


def _wait_for_mutation(
    context: dagster.OpExecutionContext,
    cluster: ClickhouseCluster,
    table: str,
    mutation: MutationWaiter,
    label: str,
    stall_timeout: float,
    wait_deadline: float,
) -> None:
    """Block until the mutation finishes on every host, failing only when it is stuck.

    MutationWaiter.wait polls is_done forever and never reads latest_fail_reason, so a mutation
    failing on every attempt is indistinguishable from a slow one. MutationProgress arbitrates
    between the two, and the raised Failure names the batch and mutation ids for diagnosis.

    Every host is polled, not one: a mutation can fail on a single replica, and asking only one
    host would poll a stuck mutation forever.
    """
    ids = tuple(mutation.mutation_ids)

    def status(client: Client) -> MutationStatus:
        [[done, visible, parts_to_do, fail_time, fail_reason, server_now]] = client.execute(
            """
            SELECT
                countIf(is_done) = count() AND count() = %(expected)s,
                count() = %(expected)s,
                sum(parts_to_do),
                max(latest_fail_time),
                argMax(latest_fail_reason, latest_fail_time),
                now()
            FROM system.mutations
            WHERE database = %(database)s AND table = %(table)s AND mutation_id IN %(ids)s
            """,
            {"database": settings.CLICKHOUSE_DATABASE, "table": table, "ids": ids, "expected": len(ids)},
        )
        return MutationStatus(
            done=bool(done),
            visible=bool(visible),
            parts_to_do=int(parts_to_do or 0),
            # latest_fail_time is the epoch when no attempt ever failed, so the reason is the
            # authoritative "has failed" signal and the time is only meaningful alongside it.
            latest_fail_time=fail_time if fail_reason else None,
            latest_fail_reason=fail_reason or "",
            server_now=server_now,
        )

    progress = MutationProgress(stall_timeout=stall_timeout, wait_deadline=wait_deadline)
    while True:
        statuses = list(cluster.map_all_hosts(status).result().values())
        if statuses and all(s.done for s in statuses):
            return

        parts_to_do = sum(s.parts_to_do for s in statuses)
        fail_reason = next((s.latest_fail_reason for s in statuses if s.latest_fail_reason), "")
        try:
            progress.observe(statuses, time.monotonic())
        except MutationStalled as stalled:
            raise dagster.Failure(
                description=f"mutation on {table} looks stuck: {fail_reason or stalled}",
                metadata={
                    "batch": dagster.MetadataValue.text(label),
                    "mutation_ids": dagster.MetadataValue.text(", ".join(ids)),
                    "parts_to_do": dagster.MetadataValue.int(parts_to_do),
                    "latest_fail_reason": dagster.MetadataValue.text(fail_reason),
                    "stall": dagster.MetadataValue.text(str(stalled)),
                },
            ) from stalled

        if fail_reason:
            context.log.warning(
                "%s: %s parts remaining, ClickHouse retrying after: %s", label, parts_to_do, fail_reason
            )
        else:
            context.log.info("%s: %s parts remaining", label, parts_to_do)
        time.sleep(MUTATION_POLL_SECONDS)


@dataclass(frozen=True, kw_only=True)
class TeamRange:
    """One inclusive [low, high] slice of the candidate team ids."""

    low: int
    high: int


def _team_ranges(team_ids: list[int], batches: int) -> list[TeamRange]:
    """Cut sorted team ids into contiguous, inclusive [low, high] ranges that cover all of them.

    Bounds are real team ids rather than an even split of the id space, so batches hold roughly
    equal numbers of teams however sparsely the ids are distributed. They are also literal
    integers, which keeps each batch's mutation command text short and identical across reruns —
    that is what lets MutationRunner re-attach to a batch instead of reissuing it.
    """
    if not team_ids:
        return []
    ordered = sorted(team_ids)
    size = max(1, ceil(len(ordered) / max(1, batches)))
    return [
        TeamRange(low=chunk[0], high=chunk[-1])
        for chunk in (ordered[i : i + size] for i in range(0, len(ordered), size))
    ]


def _run_ordered_delete(
    context: dagster.OpExecutionContext,
    cluster: ClickhouseCluster,
    table: str,
    dictionary: SnapshotDictionary,
    key_tuple: str,
    team_ranges: list[TeamRange],
    metrics: MetricsClient,
    stall_timeout: float,
    wait_deadline: float,
) -> int:
    """Delete every snapshotted row from `table`, oldest version first.

    Two passes per team range, in this order and never merged:

      A. every version below the key's snapshot max
      B. the max itself

    Pass A can never remove the tombstone, so while it runs the surviving max for each key is
    still the tombstone and readers keep resolving the key as deleted. Only once A has finished
    for a range does B remove the last row, and by then there is no older version left to fall
    back to. Doing this in one pass instead would let an interrupted mutation strip the tombstone
    from a part while an older live row survived in another, handing the key back to a person
    this run is about to delete.

    Both passes are bounded by the snapshot's max_version, so rows written after the snapshot are
    never touched by a run that did not observe them.
    """
    lookup = f"dictGetOrNull({dictionary.qualified_name!r}, 'max_version', {key_tuple}) as snapshot_max"
    passes = (
        ("below_max", f"isNotNull({lookup}) AND version < snapshot_max"),
        ("max", f"isNotNull({lookup}) AND version <= snapshot_max"),
    )

    batches = 0
    for team_range in team_ranges:
        for pass_name, key_predicate in passes:
            predicate = f"team_id >= {team_range.low} AND team_id <= {team_range.high} AND {key_predicate}"
            runner = LightweightDeleteMutationRunner(
                table=table,
                predicate=predicate,
                settings=settings_with_log_comment(context),
            )
            # Both tables are replicated and not sharded, so a mutation started on one host
            # reaches all of them.
            mutation = cluster.any_host(runner).result()
            _wait_for_mutation(
                context,
                cluster,
                table,
                mutation,
                f"{table}:{team_range.low}-{team_range.high}:{pass_name}",
                stall_timeout,
                wait_deadline,
            )
            _emit(metrics, "clickhouse_cleanup_delete_pass_total", {"table": table, "pass": pass_name})
            batches += 1

    context.log.info("%s: completed %s ordered delete mutations", table, batches)
    return batches


def _require_snapshot_intact(cluster: ClickhouseCluster, table: SnapshotTable, recorded: int) -> None:
    """Fail the run if the snapshot lost rows since it was recorded.

    The 14-day TTL drops a run's partition unconditionally, so a run stalled past it would
    otherwise sweep from a silently shrunken worklist, and nothing would distinguish
    "under-deleted" from "had fewer rows".
    """
    current = cluster.any_host_by_role(table.distinct_key_count, NodeRole.DATA).result()
    if current != recorded:
        raise dagster.Failure(
            f"{table.table_name} holds {current} keys for this run but {recorded} were snapshotted;"
            " the snapshot TTL has likely expired mid-run, so re-run from a fresh snapshot"
        )


@dagster.op
def delete_orphaned_distinct_ids(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    run: CleanupRun,
) -> CleanupRun:
    """Remove every version of the qualifying distinct id mappings, oldest version first."""
    if run.dry_run:
        context.log.info("dry run: skipping the delete from %s", PERSON_DISTINCT_ID2_TABLE)
        return run

    _require_snapshot_intact(cluster, run.orphaned, run.orphaned_count)
    ranges = _team_ranges(cluster.any_host_by_role(run.orphaned.team_ids, NodeRole.DATA).result(), run.team_batches)
    context.add_output_metadata({"team_ranges": dagster.MetadataValue.int(len(ranges))})

    _run_ordered_delete(
        context,
        cluster,
        PERSON_DISTINCT_ID2_TABLE,
        run.orphaned_dictionary,
        "(team_id, distinct_id)",
        ranges,
        MetricsClient(cluster),
        run.mutation_stall_timeout,
        run.mutation_wait_deadline,
    )

    return replace(run, distinct_ids_deleted_at=datetime.now(UTC))


@dagster.op
def persist_deleted_persons(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    persons_database_url: dagster.ResourceParam[str],
    run: CleanupRun,
) -> CleanupRun:
    """Hand the swept persons to Postgres, before the step that makes them unrecoverable.

    The queue is advisory, never authoritative. Rows sit here until the drain runs, so a person
    can be revived after being queued no matter how carefully this op checks. ClickHouse also
    trails Postgres, so a person revived in Postgres can still read as deleted here. The drain
    has to re-verify each person against Postgres before deleting it.
    """
    if run.dry_run:
        context.log.info("dry run: skipping the write to %s", PG_CLEANUP_QUEUE_TABLE)
        return run

    # Connected here rather than at resource init: a connect failure at init happens before the
    # step exists, so no failure hook runs and the run's dictionaries are stranded. Failing
    # inside the op is a step failure, which is what lets drop_assets_on_failure fire. It also
    # keeps a dry run from dialing Postgres at all.
    persons_database = psycopg2.connect(persons_database_url, connect_timeout=10)

    def read_page(client: Client, after: tuple[int, str] | None) -> list[tuple[int, str]]:
        # Reads the snapshot directly rather than the dictionary's query, so adding attributes to
        # the dictionary cannot silently change the shape of what gets queued. Keyset pagination
        # over (team_id, person_id) follows the table's sort key, and DISTINCT collapses the
        # duplicate versions a retried snapshot insert can leave in the ReplacingMergeTree.
        page_filter = "AND (team_id, person_id) > (%(after_team)s, toUUID(%(after_person)s))" if after else ""
        return client.execute(
            f"""
            SELECT DISTINCT team_id, person_id FROM {run.persons.qualified_name}
            WHERE run_id = %(run_id)s
              AND (team_id, person_id) NOT IN ({run.revived.run_keys_query})
              {page_filter}
            ORDER BY team_id, person_id
            LIMIT %(limit)s
            """,
            {
                "run_id": run.persons.run_id,
                "limit": PERSIST_PAGE_SIZE,
                "after_team": after[0] if after else 0,
                "after_person": after[1] if after else "",
            },
            settings=run.query_settings,
        )

    deleted_at = run.distinct_ids_deleted_at
    written = 0
    after: tuple[int, str] | None = None
    try:
        with persons_database.cursor() as cursor:
            cursor.execute("SET application_name = 'clickhouse_cleanup'")
            # Bounded so a lock conflict on the queue fails the page instead of holding a transaction
            # open on the persons writer; the per-page upsert is idempotent, so a retry is safe.
            cursor.execute("SET statement_timeout = '120s'")
            cursor.execute("SET lock_timeout = '10s'")
            while True:
                page = cluster.any_host_by_role(partial(read_page, after=after), NodeRole.DATA).result()
                if not page:
                    break
                # A person can be deleted, drained, re-created and deleted again under the same uuid,
                # and the drain only looks at rows where cleaned_at is null. Leaving an already-cleaned
                # row untouched would drop that second deletion on the floor and leak its Postgres rows
                # for good, so the conflict re-arms the row instead of ignoring it. The WHERE keeps a
                # retried op from rewriting rows that already hold these values: an unconditional
                # DO UPDATE writes a new tuple version per row, so a retry over millions of rows would
                # leave that many dead tuples for the persons writer to vacuum.
                execute_values(
                    cursor,
                    f"""
                    INSERT INTO {PG_CLEANUP_QUEUE_TABLE} (team_id, person_uuid, deleted_at)
                    VALUES %s
                    ON CONFLICT (team_id, person_uuid) DO UPDATE
                    SET deleted_at = EXCLUDED.deleted_at, cleaned_at = NULL
                    WHERE {PG_CLEANUP_QUEUE_TABLE}.cleaned_at IS NOT NULL
                       OR {PG_CLEANUP_QUEUE_TABLE}.deleted_at IS DISTINCT FROM EXCLUDED.deleted_at
                    """,
                    [(team_id, str(person_id), deleted_at) for team_id, person_id in page],
                    page_size=1000,
                )
                # The conflict guard makes rowcount "rows changed", not "rows queued"; the metric is
                # the queued set, which is the page.
                written += len(page)
                # Commit per page: the upsert makes replays idempotent, and one transaction across
                # millions of rows would hold WAL and xmin on the persons writer for the whole op.
                persons_database.commit()
                if len(page) < PERSIST_PAGE_SIZE:
                    break
                last_team, last_person = page[-1]
                after = (last_team, str(last_person))
    finally:
        persons_database.close()

    context.add_output_metadata({"queued_for_postgres": dagster.MetadataValue.int(written)})
    return run


@dagster.op
def delete_persons(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    run: CleanupRun,
) -> CleanupRun:
    """Remove the snapshotted persons from the ClickHouse person table, oldest version first.

    `person` carries the same tombstone-on-top-of-live-versions shape as person_distinct_id2, so
    it has the same resurrection hazard and gets the same two ordered passes.
    """
    if run.dry_run:
        context.log.info("dry run: skipping the delete from %s", PERSONS_TABLE)
        return run

    _require_snapshot_intact(cluster, run.persons, run.persons_count)
    ranges = _team_ranges(cluster.any_host_by_role(run.persons.team_ids, NodeRole.DATA).result(), run.team_batches)
    context.add_output_metadata({"team_ranges": dagster.MetadataValue.int(len(ranges))})

    _run_ordered_delete(
        context,
        cluster,
        PERSONS_TABLE,
        run.persons_dictionary,
        "(team_id, id)",
        ranges,
        MetricsClient(cluster),
        run.mutation_stall_timeout,
        run.mutation_wait_deadline,
    )

    return run


@dagster.op
def drop_snapshot_assets(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    run: CleanupRun,
) -> None:
    """Drop this run's dictionaries and clear the rows they read."""
    if not run.cleanup:
        context.log.info("cleanup disabled, leaving the assets for run %s in place", run.persons.run_id)
        return

    # The dictionaries read from the tables, so they have to go first.
    for dictionary in (run.orphaned_dictionary, run.persons_dictionary):
        cluster.map_all_hosts(dictionary.drop).result()
    # The TTL would reap these anyway. Clearing them now keeps the shared tables small enough that
    # a run's own rows stay cheap to read.
    for table in run.all_tables:
        cluster.any_host_by_role(table.drop_run_partition, NodeRole.DATA).result()


def _drop_dictionary(client: Client, qualified_name: str) -> None:
    client.execute(f"DROP DICTIONARY IF EXISTS {qualified_name} SYNC")


def _kill_and_drop_run_assets(cluster: ClickhouseCluster, run_id: str) -> None:
    """Kill the mutations that still read a run's dictionaries, then drop the dictionaries.

    Kill first: a dropped dictionary fails its readers. Killing a half-applied ordered delete
    is safe because each key's tombstone stays the surviving max version.
    """

    def kill_run_mutations(client: Client) -> None:
        for table in (PERSON_DISTINCT_ID2_TABLE, PERSONS_TABLE):
            client.execute(
                f"KILL MUTATION WHERE database = %(database)s AND table = %(table)s"
                f" AND NOT is_done AND command LIKE %(pattern)s SYNC",
                {
                    "database": settings.CLICKHOUSE_DATABASE,
                    "table": table,
                    "pattern": f"%_{run_id}_dictionary%",
                },
            )

    cluster.map_all_hosts(kill_run_mutations).result()

    for table_name in CLEANUP_SNAPSHOT_TABLES:
        name = f"{settings.CLICKHOUSE_DATABASE}.{table_name}_{run_id}_dictionary"
        cluster.map_all_hosts(partial(_drop_dictionary, qualified_name=name)).result()


# Exactly the per-run dictionary names this job generates; the janitor touches nothing else.
_RUN_SCOPED_DICTIONARY = re.compile(
    r"^(?:" + "|".join(re.escape(t) for t in CLEANUP_SNAPSHOT_TABLES) + r")"
    r"_([0-9a-f]{8}_[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{12})_dictionary$"
)

# Statuses in which a run can no longer be using its dictionaries. Sourced from the public enum
# rather than dagster's private FINISHED_STATUSES so an upstream rename cannot break the import.
_TERMINAL_RUN_STATUSES = frozenset(
    {dagster.DagsterRunStatus.SUCCESS, dagster.DagsterRunStatus.FAILURE, dagster.DagsterRunStatus.CANCELED}
)


def reap_stranded_run_assets(context: dagster.OpExecutionContext, cluster: ClickhouseCluster) -> int:
    """Drop dictionaries left by finished sweep runs, and return how many runs were reaped.

    Cancellation, run-worker crashes, and pre-step failures skip the failure hook, and
    dictionaries have no TTL. Only runs this instance knows to be finished are reaped:
    an active run's assets are in use, and an unknown run id cannot be proven dead.
    """
    try:
        current = context.run_id.replace("-", "_")

        def dictionary_names(client: Client) -> list[str]:
            rows = client.execute(
                "SELECT name FROM system.dictionaries WHERE database = %(database)s",
                {"database": settings.CLICKHOUSE_DATABASE},
            )
            return [row[0] for row in rows]

        names: set[str] = set()
        for host_names in cluster.map_all_hosts(dictionary_names).result().values():
            names.update(host_names)

        reaped: list[str] = []
        for name in sorted(names):
            match = _RUN_SCOPED_DICTIONARY.match(name)
            if not match or match.group(1) == current or match.group(1) in reaped:
                continue
            run_id = match.group(1)
            stranded_run = context.instance.get_run_by_id(run_id.replace("_", "-"))
            if stranded_run is None:
                context.log.warning("not reaping %s: this instance does not know run %s", name, run_id)
                continue
            if stranded_run.status not in _TERMINAL_RUN_STATUSES:
                continue
            context.log.warning("reaping stranded assets of finished run %s", run_id)
            try:
                _kill_and_drop_run_assets(cluster, run_id)
            except Exception:
                # One unreapable run must not shadow the later ones, or block them forever.
                context.log.exception("failed to reap run %s", run_id)
                _emit(MetricsClient(cluster), "clickhouse_cleanup_stranded_runs_unreapable", {})
                continue
            reaped.append(run_id)

        if reaped:
            _emit(MetricsClient(cluster), "clickhouse_cleanup_stranded_runs_reaped", {}, value=len(reaped))
        return len(reaped)
    except Exception:
        # Leftovers cost memory, not correctness, so a broken janitor must not block the sweep.
        context.log.exception("failed to reap stranded run assets")
        return 0


@dagster.failure_hook(required_resource_keys={"cluster"})
def drop_assets_on_failure(context: dagster.HookContext) -> None:
    """Drop this run's dictionaries when an op fails.

    Dagster skips downstream ops after a failure, so drop_snapshot_assets never runs and the
    dictionaries would survive on the cluster and accumulate across failures. Their names come
    from the run id alone, so this needs nothing from the failed op.

    This ignores the cleanup flag on purpose. A stranded dictionary holds its whole key set in
    memory on every host, which costs more than the ability to inspect it after a failure.

    The failed run's rows are left behind deliberately. They cost far less than a dictionary and
    the tables' TTL reaps them, so a failed sweep stays inspectable in the meantime.
    """
    _kill_and_drop_run_assets(context.resources.cluster, context.run_id.replace("-", "_"))


@dagster.job(hooks={drop_assets_on_failure}, tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def clickhouse_deletion_sweep_job():
    """Sweep deleted cohort memberships, then deleted persons and their distinct ids."""
    run = snapshot_orphaned_distinct_ids(snapshot_deleted_persons(clear_removed_cohort_data()))

    run = recheck_revived_persons("recheck_before_distinct_id_delete")(run)
    run = delete_orphaned_distinct_ids(run)

    # One checkpoint covers both the handoff and the person delete, so they agree on who is
    # deleted. Checking again between them would let a revival spare a person in ClickHouse
    # while its row stayed queued, and the Postgres drain would then clear a live person.
    run = recheck_revived_persons("recheck_before_person_delete")(run)
    run = persist_deleted_persons(run)

    # Each op takes the previous op's output, which is what keeps the sweeps in sequence.
    drop_snapshot_assets(delete_persons(run))
