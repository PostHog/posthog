from django.conf import settings

from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION, kafka_engine
from posthog.clickhouse.table_engines import (
    AggregatingMergeTree,
    Distributed,
    ReplicationScheme,
)
from posthog.kafka_client.topics import KAFKA_APP_METRICS

SHARDED_APP_METRICS_TABLE_ENGINE = lambda: AggregatingMergeTree(
    "sharded_app_metrics", replication_scheme=ReplicationScheme.SHARDED
)

BASE_APP_METRICS_COLUMNS = """
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
""".strip()

APP_METRICS_DATA_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS sharded_app_metrics ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'
(
    {BASE_APP_METRICS_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {SHARDED_APP_METRICS_TABLE_ENGINE()}
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, plugin_config_id, job_id, category, toStartOfHour(timestamp), error_type, error_uuid)
"""
)


DISTRIBUTED_APP_METRICS_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS app_metrics ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'
(
    {BASE_APP_METRICS_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE={Distributed(data_table="sharded_app_metrics", sharding_key="rand()")}
"""
)

KAFKA_APP_METRICS_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS kafka_app_metrics ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'
(
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
)
ENGINE={kafka_engine(topic=KAFKA_APP_METRICS)}
"""
)

APP_METRICS_MV_TABLE_SQL = (
    lambda: f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS app_metrics_mv ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'
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


TRUNCATE_APP_METRICS_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS sharded_app_metrics"

INSERT_APP_METRICS_SQL = """
INSERT INTO sharded_app_metrics (
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
    error_details,
    _timestamp,
    _offset,
    _partition
)
SELECT
    %(team_id)s,
    %(timestamp)s,
    %(plugin_config_id)s,
    %(category)s,
    %(job_id)s,
    %(successes)s,
    %(successes_on_retry)s,
    %(failures)s,
    %(error_uuid)s,
    %(error_type)s,
    %(error_details)s,
    now(),
    0,
    0
"""

QUERY_APP_METRICS_DELIVERY_RATE = """
SELECT plugin_config_id, if(total > 0, success/total, 1) as rate FROM (
    SELECT plugin_config_id, sum(successes) + sum(successes_on_retry) AS success, sum(successes) + sum(successes_on_retry) + sum(failures) AS total
    FROM app_metrics
    WHERE team_id = %(team_id)s
        AND timestamp > %(from_date)s
    GROUP BY plugin_config_id
)
"""

QUERY_APP_METRICS_TIME_SERIES = """
SELECT groupArray(date), groupArray(successes), groupArray(successes_on_retry), groupArray(failures)
FROM (
    SELECT
        date,
        sum(successes) AS successes,
        sum(successes_on_retry) AS successes_on_retry,
        sum(failures) AS failures
    FROM (
        SELECT
            dateTrunc(%(interval)s, timestamp, %(timezone)s) AS date,
            sum(successes) AS successes,
            sum(successes_on_retry) AS successes_on_retry,
            sum(failures) AS failures
        FROM app_metrics
        WHERE team_id = %(team_id)s
          AND plugin_config_id = %(plugin_config_id)s
          AND category = %(category)s
          {job_id_clause}
          AND timestamp >= %(date_from)s
          AND timestamp < %(date_to)s
        GROUP BY dateTrunc(%(interval)s, timestamp, %(timezone)s)
    )
    GROUP BY date
    ORDER BY date
    WITH FILL
        FROM dateTrunc(%(interval)s, toDateTime(%(date_from)s), %(timezone)s)
        TO dateTrunc(%(interval)s, toDateTime(%(date_to)s) + {interval_function}(1), %(timezone)s)
        STEP %(with_fill_step)s
)
"""

QUERY_APP_METRICS_ERRORS = """
SELECT error_type, count() AS count, max(timestamp) AS last_seen
FROM app_metrics
WHERE team_id = %(team_id)s
  AND plugin_config_id = %(plugin_config_id)s
  AND category = %(category)s
  {job_id_clause}
  AND timestamp >= %(date_from)s
  AND timestamp < %(date_to)s
  AND error_type <> ''
GROUP BY error_type
ORDER BY count DESC
"""

QUERY_APP_METRICS_ERROR_DETAILS = """
SELECT timestamp, error_uuid, error_type, error_details
FROM app_metrics
WHERE team_id = %(team_id)s
  AND plugin_config_id = %(plugin_config_id)s
  AND category = %(category)s
  AND error_type = %(error_type)s
  {job_id_clause}
ORDER BY timestamp DESC
LIMIT 20
"""
