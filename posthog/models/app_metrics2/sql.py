from django.conf import settings

from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION, kafka_engine, ttl_period
from posthog.clickhouse.table_engines import (
    AggregatingMergeTree,
    Distributed,
    ReplicationScheme,
)
from posthog.kafka_client.topics import KAFKA_APP_METRICS2

APP_METRICS2_TTL_DAYS = 90

SHARDED_APP_METRICS2_TABLE_ENGINE = lambda: AggregatingMergeTree(
    "sharded_app_metrics2", replication_scheme=ReplicationScheme.SHARDED
)

BASE_APP_METRICS2_COLUMNS = """
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    -- The name of the service or product that generated the metrics.
    -- Examples: plugins, hog
    app_source LowCardinality(String),
    -- An id for the app source.
    -- Set app_source to avoid collision with ids from other app sources if the id generation is not safe.
    -- Examples: A plugin id, a hog application id
    app_source_id String,
    -- A secondary id e.g. for the instance of app_source that generated this metric.
    -- This may be ommitted if app_source is a singleton.
    -- Examples: A plugin config id, a hog application config id
    instance_id String,
    successes SimpleAggregateFunction(sum, Int64),
    skipped SimpleAggregateFunction(sum, Int64),
    failures SimpleAggregateFunction(sum, Int64),
    error_type String
""".strip()

# NOTE: We have producers that take advantage of the timestamp being truncated to the hour,
# i.e. they batch up metrics and send them pre-truncated. If we ever change this truncation
# we need to revisit producers (e.g. the webhook service currently known as rusty-hook or pgqueue).
APP_METRICS2_TIMESTAMP_TRUNCATION = "toStartOfHour(timestamp)"

APP_METRICS2_DATA_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS sharded_app_metrics2 ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'
(
    {BASE_APP_METRICS2_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {SHARDED_APP_METRICS2_TABLE_ENGINE()}
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, app_source, app_source_id, instance_id, {APP_METRICS2_TIMESTAMP_TRUNCATION}, error_type)
{ttl_period("timestamp", APP_METRICS2_TTL_DAYS, unit="DAY")}
"""
)

DISTRIBUTED_APP_METRICS2_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS app_metrics2 ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'
(
    {BASE_APP_METRICS2_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE={Distributed(data_table="sharded_app_metrics2", sharding_key="rand()")}
"""
)

KAFKA_APP_METRICS2_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS kafka_app_metrics2 ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'
(
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    app_source LowCardinality(String),
    app_source_id String,
    instance_id String,
    successes Int64,
    skipped Int64,
    failures Int64,
    error_type String
)
ENGINE={kafka_engine(topic=KAFKA_APP_METRICS2)}
"""
)

APP_METRICS2_MV_TABLE_SQL = (
    lambda: f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS app_metrics2_mv ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'
TO {settings.CLICKHOUSE_DATABASE}.sharded_app_metrics2
AS SELECT
team_id,
timestamp,
app_source,
app_source_id,
instance_id,
successes,
skipped,
failures,
error_type
FROM {settings.CLICKHOUSE_DATABASE}.kafka_app_metrics2
"""
)

TRUNCATE_APP_METRICS2_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS sharded_app_metrics2"

INSERT_APP_METRICS2_SQL = """
INSERT INTO sharded_app_metrics2 (
    team_id,
    timestamp,
    app_source,
    app_source_id,
    instance_id,
    successes,
    skipped,
    failures,
    error_type,
    _timestamp,
    _offset,
    _partition
)
SELECT
    %(team_id)s,
    %(timestamp)s,
    %(app_source)s,
    %(app_source_id)s,
    %(instance_id)s,
    %(successes)s,
    %(skipped)s,
    %(failures)s,
    %(error_type)s,
    now(),
    0,
    0
"""

QUERY_APP_METRICS2_DELIVERY_RATE = """
SELECT app_source, app_source_id, instance_id, if(total > 0, success/total, 1) as rate FROM (
    SELECT app_source, app_source_id, instance_id, sum(successes) + sum(skipped) AS success, sum(successes) + sum(skipped) + sum(failures) AS total
    FROM app_metrics2
    WHERE team_id = %(team_id)s
        AND timestamp > %(from_date)s
    GROUP BY app_source, app_source_id, instance_id
)
"""

# For composeWebhook apps we report successes and failures in two steps
# 1. running the composeWebhook function
# 2. rusty hook sending the webhook
# Users don't care that there are two steps, we'll want to show them the
# success count after step 2, but for failures we'll want to add them up
QUERY_APP_METRICS2_TIME_SERIES = """
SELECT groupArray(date), groupArray(successes), groupArray(skipped), groupArray(failures)
FROM (
    SELECT
        date,
        sum(CASE WHEN category = 'composeWebhook' THEN 0 ELSE successes END) AS successes,
        sum(skipped) AS skipped,
        sum(failures) AS failures
    FROM (
        SELECT
            category,
            dateTrunc(%(interval)s, timestamp, %(timezone)s) AS date,
            sum(successes) AS successes,
            sum(skipped) AS skipped,
            sum(failures) AS failures
        FROM app_metrics2
        WHERE team_id = %(team_id)s
          AND app_source = %(app_source)s
          AND app_source_id = %(app_source_id)s
          AND instance_id = %(instance_id)s
          {category_clause}
          {job_id_clause}
          AND timestamp >= %(date_from)s
          AND timestamp < %(date_to)s
        GROUP BY dateTrunc(%(interval)s, timestamp, %(timezone)s), category
    )
    GROUP BY date
    ORDER BY date
    WITH FILL
        FROM dateTrunc(%(interval)s, toDateTime(%(date_from)s), %(timezone)s)
        TO dateTrunc(%(interval)s, toDateTime(%(date_to)s) + {interval_function}(1), %(timezone)s)
        STEP %(with_fill_step)s
)
"""

QUERY_APP_METRICS2_ERRORS = """
SELECT error_type, count() AS count, max(timestamp) AS last_seen
FROM app_metrics2
WHERE team_id = %(team_id)s
  AND app_source = %(app_source)s
  AND app_source_id = %(app_source_id)s
  AND instance_id = %(instance_id)s
  {category_clause}
  {job_id_clause}
  AND timestamp >= %(date_from)s
  AND timestamp < %(date_to)s
  AND error_type <> ''
GROUP BY error_type
ORDER BY count DESC
"""

# TODO: This will need to be adjusted to query the log_entries table for error detail information,
#       which will be sent there instead of stored alongside the metrics like they were in `app_metrics` (1)
QUERY_APP_METRICS2_ERROR_DETAILS = """
SELECT timestamp, error_type
FROM app_metrics2
WHERE team_id = %(team_id)s
  AND app_source = %(app_source)s
  AND app_source_id = %(app_source_id)s
  AND instance_id = %(instance_id)s
  AND error_type = %(error_type)s
  {category_clause}
  {job_id_clause}
ORDER BY timestamp DESC
LIMIT 20
"""
