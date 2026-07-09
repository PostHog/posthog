from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.web_stats_paths_preaggregated_sql import (
    DROP_SHARDED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE_SQL,
    DROP_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE_SQL,
)

operations = [
    # The pathkey colocation experiment (migration 0278) never grew a read path and its
    # dual-write was removed; drop the distributed entrypoint first so nothing can route
    # writes mid-migration, then the sharded data table. Mirrors 0278's topology:
    # distributed on DATA nodes, sharded on AUX.
    run_sql_with_exceptions(
        DROP_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DROP_SHARDED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
]
