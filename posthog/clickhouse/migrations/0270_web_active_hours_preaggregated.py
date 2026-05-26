from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.web_active_hours_preaggregated_sql import (
    DISTRIBUTED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE_SQL,
    SHARDED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE_SQL,
)

# Backs the web analytics Active Hours tile lazy precompute (see
# `products/web_analytics/backend/hogql_queries/web_active_hours_lazy_precompute.py`).
# Follows the same 3-op AUX/DATA convention as the other web-analytics precompute
# migrations (0263, 0260, 0259): sharded data table on AUX, distributed read
# table on DATA, distributed read table on AUX for operator convenience.
operations = [
    # Sharded data table on AUX — small precompute table, never JOINed against
    # events, so it stays off the main DATA cluster.
    run_sql_with_exceptions(
        SHARDED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    # Distributed read table on DATA — production query path; fan-outs resolve
    # to AUX shards via the Distributed engine's `cluster=AUX`.
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # Same distributed table on AUX — lets operators run ad-hoc SELECTs directly
    # from an AUX node without bouncing through DATA. No production cost.
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
]
