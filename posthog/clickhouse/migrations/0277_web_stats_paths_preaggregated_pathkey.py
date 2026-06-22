from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.web_stats_paths_preaggregated_sql import (
    DISTRIBUTED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE_SQL,
    SHARDED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE_SQL,
)

operations = [
    # Breakdown-key colocation variant of web_stats_paths_preaggregated; same
    # AUX-sharded + DATA-distributed topology as migration 0260.
    run_sql_with_exceptions(
        SHARDED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
]
