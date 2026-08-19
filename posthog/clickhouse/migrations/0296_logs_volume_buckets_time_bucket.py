from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs.logs_volume_buckets import (
    DISTRIBUTED_TABLE_NAME,
    LOGS_VOLUME_BUCKETS_DISTRIBUTED_TABLE_SQL,
    LOGS_VOLUME_BUCKETS_TABLE_SQL,
    TABLE_NAME,
)

# Renames bucket_start to time_bucket to match the other logs tables. RENAME
# COLUMN is impossible here — the column is part of the key expression
# (ORDER BY / PARTITION BY / TTL), which ClickHouse rejects with Code 524 —
# so this drops and recreates instead. Safe only because the table is empty:
# it shipped in 0294 and the aggregation writer does not exist yet.

DROP_DISTRIBUTED_SQL = f"DROP TABLE IF EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{DISTRIBUTED_TABLE_NAME} SYNC"
DROP_LOCAL_SQL = f"DROP TABLE IF EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME} SYNC"

operations = [
    run_sql_with_exceptions(DROP_DISTRIBUTED_SQL, node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(DROP_LOCAL_SQL, node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS_VOLUME_BUCKETS_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS_VOLUME_BUCKETS_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
]
