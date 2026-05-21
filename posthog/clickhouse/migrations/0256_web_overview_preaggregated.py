from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.web_overview_preaggregated_sql import (
    DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL,
    SHARDED_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL,
)

operations = [
    # Sharded data table on AUX (the precompute table is small and never JOINed
    # against events — keeping it off the main DATA cluster avoids contention).
    run_sql_with_exceptions(
        SHARDED_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    # Distributed read table on DATA — queries fan out from data nodes and
    # resolve to AUX shards via the Distributed engine's `cluster=AUX` setting.
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
]
