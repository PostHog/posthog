from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.web_stats_paths_preaggregated_sql import (
    DISTRIBUTED_WEB_STATS_PATHS_PREAGGREGATED_TABLE_SQL,
    SHARDED_WEB_STATS_PATHS_PREAGGREGATED_TABLE_SQL,
)

operations = [
    # Sharded data table on AUX — matches the web_overview_preaggregated convention
    # (migration 0256). The Distributed table below targets `cluster=AUX`, so the
    # backing local table must live there too; otherwise the distributed engine
    # has no shards to fan out to in environments where AUX != DATA.
    run_sql_with_exceptions(
        SHARDED_WEB_STATS_PATHS_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    # Distributed read table on DATA — queries fan out from data nodes and
    # resolve to AUX shards via the Distributed engine's `cluster=AUX` setting.
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_STATS_PATHS_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
]
