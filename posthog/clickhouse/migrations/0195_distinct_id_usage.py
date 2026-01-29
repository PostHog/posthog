from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.distinct_id_usage.sql import (
    DISTINCT_ID_USAGE_DATA_TABLE_SQL,
    DISTINCT_ID_USAGE_MV_SQL,
    WRITABLE_DISTINCT_ID_USAGE_TABLE_SQL,
)

operations = [
    # Data table on all data + coordinator nodes (non-sharded, replicated)
    run_sql_with_exceptions(
        DISTINCT_ID_USAGE_DATA_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    # Writable distributed table on data nodes
    run_sql_with_exceptions(
        WRITABLE_DISTINCT_ID_USAGE_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # Materialized view on data nodes (triggers on sharded_events inserts)
    run_sql_with_exceptions(
        DISTINCT_ID_USAGE_MV_SQL(),
        node_roles=[NodeRole.DATA],
    ),
]
