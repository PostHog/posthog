"""Persisted worklists for the weekly ClickHouse cleanup sweep.

The sweep destroys the tombstones its own worklists are derived from, so each stage has to be
frozen before the first mutation. Runs share these tables and scope their rows by `run_id`
instead of each creating and dropping their own, which would churn table DDL across every node
every week. `run_id` leads every sort key so a run reads only its own rows through the primary
index.
"""

from posthog.clickhouse.table_engines import ReplacingMergeTree

CLEANUP_DELETED_PERSONS_TABLE = "clickhouse_cleanup_deleted_persons"
CLEANUP_REVIVED_PERSONS_TABLE = "clickhouse_cleanup_revived_persons"
CLEANUP_ORPHANED_DISTINCT_IDS_TABLE = "clickhouse_cleanup_orphaned_distinct_ids"
CLEANUP_REVIVED_DISTINCT_IDS_TABLE = "clickhouse_cleanup_revived_distinct_ids"

# A run's rows stay readable for a fortnight so a failed weekly sweep can still be inspected on the
# next working day. A successful run clears its own rows, so this only ever covers failures.
CLEANUP_SNAPSHOT_TTL_DAYS = 14


def _cleanup_snapshot_table_sql(table_name: str, columns: str, sort_key: str) -> str:
    # Partitioning by run id makes clearing a finished run a metadata-only DROP PARTITION instead
    # of a mutation that rewrites every part. created_at is the ReplacingMergeTree version, and
    # its sub-second resolution is what makes a retried populate deterministic: two inserts of the
    # same key in the same second would otherwise tie and let merge order pick the survivor.
    # ttl_only_drop_parts stops TTL merges from rewriting a part that holds any expired row; the
    # TTL is a backstop for failed runs, so reclaiming whole parts late beats weekly rewrites.
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    run_id String,
    {columns},
    created_at DateTime64(6, 'UTC') DEFAULT now64()
) ENGINE = {engine}
PARTITION BY run_id
ORDER BY (run_id, {sort_key})
TTL created_at + INTERVAL {ttl_days} DAY
SETTINGS ttl_only_drop_parts = 1
""".format(
        table_name=table_name,
        columns=columns,
        engine=ReplacingMergeTree(table_name, ver="created_at"),
        sort_key=sort_key,
        ttl_days=CLEANUP_SNAPSHOT_TTL_DAYS,
    )


def _drop_cleanup_snapshot_table_sql(table_name: str) -> str:
    return f"""
DROP TABLE IF EXISTS {table_name}
"""


def CLEANUP_DELETED_PERSONS_TABLE_SQL():
    """Persons the run will delete, one row each, with the version the run observed as latest.

    `max_version` bounds the delete so a version written after the snapshot survives a run that
    never saw it. It matches `person.version` (UInt64) so the dictionary attribute the delete
    predicate reads compares against the source column without promotion.
    """
    return _cleanup_snapshot_table_sql(
        CLEANUP_DELETED_PERSONS_TABLE,
        "team_id Int64, person_id UUID, max_version UInt64",
        "team_id, person_id",
    )


def CLEANUP_REVIVED_PERSONS_TABLE_SQL():
    """Snapshotted persons that came back to life mid-run, and so must not be deleted.

    Every dictionary over the worklists anti-joins this table, which is how a checkpoint drops a
    key without mutating the worklist it came from.
    """
    return _cleanup_snapshot_table_sql(
        CLEANUP_REVIVED_PERSONS_TABLE,
        "team_id Int64, person_id UUID",
        "team_id, person_id",
    )


def CLEANUP_ORPHANED_DISTINCT_IDS_TABLE_SQL():
    """Distinct id mappings the run will delete, with the reason each one qualified.

    `own_tombstone` distinguishes a mapping deleted in its own right from one deleted because its
    owning person is going away. `max_version` matches `person_distinct_id2.version` (Int64).
    """
    return _cleanup_snapshot_table_sql(
        CLEANUP_ORPHANED_DISTINCT_IDS_TABLE,
        "team_id Int64, distinct_id String, person_id UUID, own_tombstone UInt8, max_version Int64",
        "team_id, distinct_id",
    )


def CLEANUP_REVIVED_DISTINCT_IDS_TABLE_SQL():
    """Snapshotted distinct id mappings that stopped qualifying mid-run."""
    return _cleanup_snapshot_table_sql(
        CLEANUP_REVIVED_DISTINCT_IDS_TABLE,
        "team_id Int64, distinct_id String",
        "team_id, distinct_id",
    )


def DROP_CLEANUP_DELETED_PERSONS_TABLE_SQL():
    return _drop_cleanup_snapshot_table_sql(CLEANUP_DELETED_PERSONS_TABLE)


def DROP_CLEANUP_REVIVED_PERSONS_TABLE_SQL():
    return _drop_cleanup_snapshot_table_sql(CLEANUP_REVIVED_PERSONS_TABLE)


def DROP_CLEANUP_ORPHANED_DISTINCT_IDS_TABLE_SQL():
    return _drop_cleanup_snapshot_table_sql(CLEANUP_ORPHANED_DISTINCT_IDS_TABLE)


def DROP_CLEANUP_REVIVED_DISTINCT_IDS_TABLE_SQL():
    return _drop_cleanup_snapshot_table_sql(CLEANUP_REVIVED_DISTINCT_IDS_TABLE)


CLEANUP_SNAPSHOT_TABLES = (
    CLEANUP_DELETED_PERSONS_TABLE,
    CLEANUP_REVIVED_PERSONS_TABLE,
    CLEANUP_ORPHANED_DISTINCT_IDS_TABLE,
    CLEANUP_REVIVED_DISTINCT_IDS_TABLE,
)

CLEANUP_SNAPSHOT_TABLE_SQL = (
    CLEANUP_DELETED_PERSONS_TABLE_SQL,
    CLEANUP_REVIVED_PERSONS_TABLE_SQL,
    CLEANUP_ORPHANED_DISTINCT_IDS_TABLE_SQL,
    CLEANUP_REVIVED_DISTINCT_IDS_TABLE_SQL,
)

DROP_CLEANUP_SNAPSHOT_TABLE_SQL = (
    DROP_CLEANUP_DELETED_PERSONS_TABLE_SQL,
    DROP_CLEANUP_REVIVED_PERSONS_TABLE_SQL,
    DROP_CLEANUP_ORPHANED_DISTINCT_IDS_TABLE_SQL,
    DROP_CLEANUP_REVIVED_DISTINCT_IDS_TABLE_SQL,
)


def TRUNCATE_CLEANUP_SNAPSHOT_TABLES_SQL():
    # Unqualified so the test harness can match these against the tables ClickHouse reports as
    # empty and skip the keeper round-trip.
    return [f"TRUNCATE TABLE IF EXISTS {table_name}" for table_name in CLEANUP_SNAPSHOT_TABLES]
