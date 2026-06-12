from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.web_vitals_paths_preaggregated_sql import (
    DISTRIBUTED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE_SQL,
    SHARDED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE_SQL,
)

operations = [
    # Sharded data table on AUX (the precompute table is small and never JOINed
    # against events — keeping it off the main DATA cluster avoids contention).
    run_sql_with_exceptions(
        SHARDED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    # Distributed read table on DATA — production query path fans out from data
    # nodes and resolves to AUX shards via the Distributed engine's `cluster=AUX`.
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # Same distributed table also on AUX for ad-hoc debugging — lets operators
    # `SELECT … FROM web_vitals_paths_preaggregated` directly from an AUX node
    # instead of bouncing through DATA. Same DDL, no production cost.
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
]
