from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.web_stats_frustration_preaggregated_sql import (
    DISTRIBUTED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_SQL,
    SHARDED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_SQL,
)

operations = [
    # Sharded data table on AUX — the precompute table is small and never
    # JOINed against events, so keeping it off the main DATA cluster avoids
    # contention. The Distributed table below targets `cluster=AUX`, so the
    # backing local table must live there too; otherwise the distributed
    # engine has no shards to fan out to in environments where AUX != DATA.
    run_sql_with_exceptions(
        SHARDED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    # Distributed read table on DATA AND AUX. DATA carries the production
    # query path (queries fan out from data nodes and resolve to AUX shards
    # via the engine's `cluster=AUX`). AUX gets the same DDL so operators can
    # `SELECT … FROM web_stats_frustration_preaggregated` directly from an AUX
    # node for ad-hoc debugging without bouncing through DATA. Same DDL, no
    # production cost. Matches the convention of migration 0228
    # (experiment_metric_events_preaggregated).
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
