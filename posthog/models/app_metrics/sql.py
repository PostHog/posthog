from django.conf import settings

from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION, kafka_engine
from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_APP_METRICS

SHARDED_APP_METRICS_TABLE_ENGINE = lambda: AggregatingMergeTree(
    "sharded_app_metrics", replication_scheme=ReplicationScheme.SHARDED
)

APP_METRICS_DATA_TABLE_SQL = (
    lambda: f"""
CREATE TABLE sharded_app_metrics ON CLUSTER {settings.CLICKHOUSE_CLUSTER}
(
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    plugin_config_id Int64,
    category LowCardinality(String),
    job_id String,
    successes SimpleAggregateFunction(sum, Int64),
    successes_on_retry SimpleAggregateFunction(sum, Int64),
    failures SimpleAggregateFunction(sum, Int64),
    error_uuid UUID,
    error_type String,
    error_details String CODEC(ZSTD(3))
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {SHARDED_APP_METRICS_TABLE_ENGINE()}
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, plugin_config_id, job_id, category, toStartOfHour(timestamp), error_type, error_uuid)
"""
)

BASE_APP_METRICS_COLUMNS = """
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    plugin_config_id Int64,
    category LowCardinality(String),
    job_id String,
    successes Int64,
    successes_on_retry Int64,
    failures Int64,
    error_uuid UUID,
    error_type String,
    error_details String CODEC(ZSTD(3))
""".strip()

DISTRIBUTED_APP_METRICS_TABLE_SQL = (
    lambda: f"""
CREATE TABLE app_metrics ON CLUSTER {settings.CLICKHOUSE_CLUSTER}
(
    {BASE_APP_METRICS_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE={Distributed(data_table="sharded_app_metrics", sharding_key="rand()")}
"""
)

KAFKA_APP_METRICS_TABLE_SQL = (
    lambda: f"""
CREATE TABLE kafka_app_metrics ON CLUSTER {settings.CLICKHOUSE_CLUSTER}
(
    {BASE_APP_METRICS_COLUMNS}
)
ENGINE={kafka_engine(topic=KAFKA_APP_METRICS)}
"""
)

APP_METRICS_MV_TABLE_SQL = (
    lambda: f"""
CREATE MATERIALIZED VIEW app_metrics_mv ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'
TO {settings.CLICKHOUSE_DATABASE}.sharded_app_metrics
AS SELECT
team_id,
timestamp,
plugin_config_id,
category,
job_id,
successes,
successes_on_retry,
failures,
error_uuid,
error_type,
error_details
FROM {settings.CLICKHOUSE_DATABASE}.kafka_app_metrics
"""
)
