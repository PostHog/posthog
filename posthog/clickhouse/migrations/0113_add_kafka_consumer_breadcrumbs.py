from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions, NodeRole
from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.models.event.sql import (
    EVENTS_TABLE_JSON_MV_SQL,
    KAFKA_EVENTS_TABLE_JSON_SQL,
)

ALTER_EVENTS_TABLE_ADD_BREADCRUMBS_COLUMN = """
ALTER TABLE {table_name} {on_cluster_clause}
    ADD COLUMN IF NOT EXISTS _kafka_consumer_breadcrumbs Nullable(String)
"""

# DROP KAFKA TABLE
DROP_KAFKA_EVENTS_TABLE_JSON_TEMPLATE = """
    DROP TABLE IF EXISTS kafka_events_json {on_cluster_clause}
"""

# DROP MATERIALIZED VIEW
DROP_EVENTS_TABLE_JSON_MV_TEMPLATE = """
    DROP TABLE IF EXISTS events_json_mv {on_cluster_clause}
"""


def DROP_KAFKA_EVENTS_TABLE_JSON(on_cluster=True):
    return DROP_KAFKA_EVENTS_TABLE_JSON_TEMPLATE.format(on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster))


def DROP_EVENTS_TABLE_JSON_MV(on_cluster=True):
    return DROP_EVENTS_TABLE_JSON_MV_TEMPLATE.format(on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster))


def ADD_BREADRUMBS_COLUMNS_DISTRIBUTED_EVENTS_TABLE_SQL(on_cluster=True):
    return ALTER_EVENTS_TABLE_ADD_BREADCRUMBS_COLUMN.format(
        table_name="events", on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster)
    )


def ADD_BREADRUMBS_COLUMNS_WRITABLE_EVENTS_TABLE_SQL(on_cluster=True):
    return ALTER_EVENTS_TABLE_ADD_BREADCRUMBS_COLUMN.format(
        table_name="writable_events", on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster)
    )


def ADD_BREADRUMBS_COLUMNS_SHARDED_EVENTS_TABLE_SQL(on_cluster=True):
    return ALTER_EVENTS_TABLE_ADD_BREADCRUMBS_COLUMN.format(
        table_name="sharded_events", on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster)
    )


operations = [
    # First drop the materialized view
    run_sql_with_exceptions(DROP_EVENTS_TABLE_JSON_MV, NodeRole.WRITE),
    run_sql_with_exceptions(DROP_KAFKA_EVENTS_TABLE_JSON, NodeRole.WRITE),
    # add missing columns to all tables in correct order
    # first the sharded tables
    run_sql_with_exceptions(ADD_BREADRUMBS_COLUMNS_SHARDED_EVENTS_TABLE_SQL()),
    # second, add missing columns to writable table
    run_sql_with_exceptions(ADD_BREADRUMBS_COLUMNS_WRITABLE_EVENTS_TABLE_SQL()),
    # third,add missing columns to distributed table
    run_sql_with_exceptions(
        ADD_BREADRUMBS_COLUMNS_DISTRIBUTED_EVENTS_TABLE_SQL(on_cluster=False), node_role=NodeRole.COORDINATOR
    ),
    # recreate the kafka table
    run_sql_with_exceptions(KAFKA_EVENTS_TABLE_JSON_SQL()),
    # recreate the materialized view
    run_sql_with_exceptions(EVENTS_TABLE_JSON_MV_SQL()),
]
