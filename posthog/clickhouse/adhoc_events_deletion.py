from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import ReplacingMergeTreeDeleted

ADHOC_EVENTS_DELETION_TABLE = "adhoc_events_deletion"


def ADHOC_EVENTS_DELETION_TABLE_SQL(on_cluster=True):
    return """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    team_id Int64,
    uuid UUID,
    created_at DateTime64(6, 'UTC') DEFAULT now64(),
    deleted_at DateTime,
    is_deleted UInt8 DEFAULT 0
) ENGINE = {engine}
order by (team_id, uuid)
TTL deleted_at + INTERVAL 3 MONTH WHERE is_deleted = 1
""".format(
        table_name=ADHOC_EVENTS_DELETION_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=ReplacingMergeTreeDeleted(ADHOC_EVENTS_DELETION_TABLE, ver="deleted_at", is_deleted="is_deleted"),
    )


def DROP_ADHOC_EVENTS_DELETION_TABLE_SQL(on_cluster=True):
    return """
DROP TABLE IF EXISTS {table_name} {on_cluster_clause}
""".format(
        table_name=ADHOC_EVENTS_DELETION_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    )
