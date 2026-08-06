from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.web_bounces_dimensional_preaggregated_sql import (
    DISTRIBUTED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_SQL,
    SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_SQL,
)
from posthog.clickhouse.preaggregation.web_stats_dimensional_preaggregated_sql import (
    DISTRIBUTED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_SQL,
    SHARDED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_SQL,
)

operations = [
    # Sharded data tables on AUX (small fixed-dimension precompute tables, never
    # JOINed against events — kept off the main DATA cluster to avoid contention).
    run_sql_with_exceptions(
        SHARDED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    run_sql_with_exceptions(
        SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    # Distributed read tables on DATA — production query path fans out from data
    # nodes and resolves to AUX shards via the Distributed engine's `cluster=AUX`.
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # Same distributed tables on AUX too, for ad-hoc debugging directly from an
    # AUX node (same DDL, no production cost).
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
]
