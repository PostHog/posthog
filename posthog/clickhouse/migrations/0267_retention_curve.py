from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.retention_curve_sql import (
    DISTRIBUTED_RETENTION_CURVE_TABLE_SQL,
    SHARDED_RETENTION_CURVE_TABLE_SQL,
)

operations = [
    # Sharded curve table on AUX — small (one row per person, not per day × activity) and
    # never JOINed against events, so it stays off the main DATA cluster.
    run_sql_with_exceptions(
        SHARDED_RETENTION_CURVE_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    # Distributed read table on DATA. Production query path fans out from DATA and resolves
    # to AUX shards via the Distributed engine's `cluster=AUX` setting.
    run_sql_with_exceptions(
        DISTRIBUTED_RETENTION_CURVE_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # Same distributed table also on AUX for ad-hoc debugging.
    run_sql_with_exceptions(
        DISTRIBUTED_RETENTION_CURVE_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
]
