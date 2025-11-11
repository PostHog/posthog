from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.table_engines import MergeTreeEngine, ReplicationScheme

LLMA_METRICS_DAILY_TABLE = "llma_metrics_daily"

LLMA_METRICS_DAILY_SQL = f"""
CREATE TABLE IF NOT EXISTS {LLMA_METRICS_DAILY_TABLE}
(
    date Date,
    team_id UInt64,
    metric_name String,
    metric_value Float64
) ENGINE = {MergeTreeEngine(LLMA_METRICS_DAILY_TABLE, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toYYYYMM(date)
ORDER BY (team_id, date, metric_name)
"""

operations = [
    run_sql_with_exceptions(
        LLMA_METRICS_DAILY_SQL,
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
