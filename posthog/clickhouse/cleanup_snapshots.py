"""Persisted worklists for the weekly ClickHouse cleanup sweep.

The sweep destroys the tombstones its own worklists are derived from, so each stage has to be
frozen before the first mutation. Runs share these tables and scope their rows by `run_id`
instead of each creating and dropping their own, which would churn table DDL across every node
every week. `run_id` leads every sort key so a run reads only its own rows through the primary
index.
"""

CLEANUP_DELETED_PERSONS_TABLE = "clickhouse_cleanup_deleted_persons"
CLEANUP_REVIVED_PERSONS_TABLE = "clickhouse_cleanup_revived_persons"
CLEANUP_ORPHANED_DISTINCT_IDS_TABLE = "clickhouse_cleanup_orphaned_distinct_ids"
CLEANUP_REVIVED_DISTINCT_IDS_TABLE = "clickhouse_cleanup_revived_distinct_ids"


CLEANUP_SNAPSHOT_TABLES = (
    CLEANUP_DELETED_PERSONS_TABLE,
    CLEANUP_REVIVED_PERSONS_TABLE,
    CLEANUP_ORPHANED_DISTINCT_IDS_TABLE,
    CLEANUP_REVIVED_DISTINCT_IDS_TABLE,
)
