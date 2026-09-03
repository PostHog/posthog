from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme

# These tables were dropped in 0299, so their SQL is inlined here instead of
# living in a shared definition module.

TABLE_NAME = "logs_volume_buckets"
DISTRIBUTED_TABLE_NAME = "logs_volume_buckets_distributed"

LOGS_VOLUME_BUCKETS_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
(
    `team_id` Int32,
    `time_bucket` DateTime('UTC') CODEC(DoubleDelta, ZSTD(1)),
    `generation` UInt64,
    `service_name` LowCardinality(String),
    `namespace` LowCardinality(String),
    `environment` LowCardinality(String),
    `severity_text` LowCardinality(String),
    `log_count` UInt64
)
ENGINE = {MergeTreeEngine(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(time_bucket)
ORDER BY (team_id, time_bucket, generation, service_name, namespace, environment, severity_text)
TTL time_bucket + INTERVAL 42 DAY
SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1
"""

LOGS_VOLUME_BUCKETS_DISTRIBUTED_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{DISTRIBUTED_TABLE_NAME}
AS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
ENGINE = {Distributed(data_table=TABLE_NAME, cluster=settings.CLICKHOUSE_LOGS_CLUSTER)}
"""

operations = [
    run_sql_with_exceptions(LOGS_VOLUME_BUCKETS_TABLE_SQL, node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS_VOLUME_BUCKETS_DISTRIBUTED_TABLE_SQL, node_roles=[NodeRole.LOGS]),
]
