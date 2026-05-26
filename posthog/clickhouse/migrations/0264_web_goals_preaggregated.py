from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.web_goals_preaggregated_sql import (
    DISTRIBUTED_WEB_GOALS_PREAGGREGATED_TABLE_SQL,
    SHARDED_WEB_GOALS_PREAGGREGATED_TABLE_SQL,
)

operations = [
    # Sharded data table on AUX — same reasoning as the preceding migration
    # (0261, web_stats_frustration): the precompute table is small, never
    # JOINed against events, and `cluster=AUX` on the distributed engine
    # requires the backing local table on AUX.
    run_sql_with_exceptions(
        SHARDED_WEB_GOALS_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    # Distributed read table on DATA AND AUX — production reads originate on
    # DATA; AUX also gets the table for ad-hoc operator queries from an AUX
    # node. Matches the convention of migrations 0228 / 0261.
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_GOALS_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
