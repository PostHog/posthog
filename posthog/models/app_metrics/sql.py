from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION, kafka_engine
from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_APP_METRICS

APP_METRICS_TABLE = "app_metrics"
APP_METRICS_SHARDED_TABLE = f"sharded_{APP_METRICS_TABLE}"
APP_METRICS_MV_TABLE = f"{APP_METRICS_TABLE}_mv"
APP_METRICS_WRITABLE_TABLE = f"writable_{APP_METRICS_TABLE}"
KAFKA_APP_METRICS_TABLE = f"kafka_{APP_METRICS_TABLE}"

DROP_APP_METRICS_MV_TABLE_SQL = f"DROP TABLE IF EXISTS {APP_METRICS_MV_TABLE}"
DROP_KAFKA_APP_METRICS_TABLE_SQL = f"DROP TABLE IF EXISTS {KAFKA_APP_METRICS_TABLE}"
DROP_APP_METRICS_TABLE_SQL = f"DROP TABLE IF EXISTS {APP_METRICS_TABLE}"


def SHARDED_APP_METRICS_TABLE_ENGINE():
    return AggregatingMergeTree(APP_METRICS_SHARDED_TABLE, replication_scheme=ReplicationScheme.SHARDED)


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

# NOTE: We have producers that take advantage of the timestamp being truncated to the hour,
# i.e. they batch up metrics and send them pre-truncated. If we ever change this truncation
# we need to revisit producers (e.g. the webhook service currently known as rusty-hook or pgqueue).
APP_METRICS_TIMESTAMP_TRUNCATION = "toStartOfHour(timestamp)"

APP_METRICS_DATA_TABLE_SQL = (
    lambda on_cluster=True: f"""
CREATE TABLE IF NOT EXISTS {APP_METRICS_SHARDED_TABLE} {ON_CLUSTER_CLAUSE(on_cluster)}
(
    {BASE_APP_METRICS_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {SHARDED_APP_METRICS_TABLE_ENGINE()}
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, plugin_config_id, job_id, category, {APP_METRICS_TIMESTAMP_TRUNCATION}, error_type, error_uuid)
"""
)


DISTRIBUTED_APP_METRICS_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS {APP_METRICS_TABLE}
(
    {BASE_APP_METRICS_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE={Distributed(data_table=APP_METRICS_SHARDED_TABLE, sharding_key="rand()")}
"""
)

WRITABLE_APP_METRICS_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS {APP_METRICS_WRITABLE_TABLE}
(
    {BASE_APP_METRICS_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE={Distributed(data_table=APP_METRICS_SHARDED_TABLE, sharding_key="rand()")}
"""
)

KAFKA_APP_METRICS_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS {KAFKA_APP_METRICS_TABLE}
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


def APP_METRICS_MV_TABLE_SQL(target_table: str = APP_METRICS_WRITABLE_TABLE) -> str:
    """
    Create materialized view SQL for app_metrics.
    This must be a function to ensure CLICKHOUSE_DATABASE is evaluated at runtime.
    """
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {APP_METRICS_MV_TABLE}
TO {target_table}
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
error_details,
_timestamp,
_offset,
_partition
FROM {KAFKA_APP_METRICS_TABLE}
"""


TRUNCATE_APP_METRICS_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {APP_METRICS_SHARDED_TABLE}"

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

# For composeWebhook apps we report successes and failures in two steps
# 1. running the composeWebhook function
# 2. rusty hook sending the webhook
# Users don't care that there are two steps, we'll want to show them the
# success count after step 2, but for failures we'll want to add them up
QUERY_APP_METRICS_TIME_SERIES = """
SELECT groupArray(date), groupArray(successes), groupArray(successes_on_retry), groupArray(failures)
FROM (
    SELECT
        date,
        sum(CASE WHEN category = 'composeWebhook' THEN 0 ELSE successes END) AS successes,
        sum(successes_on_retry) AS successes_on_retry,
        sum(failures) AS failures
    FROM (
        SELECT
            category,
            dateTrunc(%(interval)s, timestamp, %(timezone)s) AS date,
            sum(successes) AS successes,
            sum(successes_on_retry) AS successes_on_retry,
            sum(failures) AS failures
        FROM app_metrics
        WHERE team_id = %(team_id)s
          AND plugin_config_id = %(plugin_config_id)s
          {category_clause}
          {job_id_clause}
          AND timestamp >= %(date_from)s
          AND timestamp < %(date_to)s
        GROUP BY dateTrunc(%(interval)s, timestamp, %(timezone)s), category
    )
    GROUP BY date
    ORDER BY date
    WITH FILL
        FROM dateTrunc(%(interval)s, toDateTime64(%(date_from)s, 0, %(timezone)s), %(timezone)s)
        TO dateTrunc(%(interval)s, toDateTime64(%(date_to)s, 0, %(timezone)s) + {interval_function}(1), %(timezone)s)
        STEP {interval_function}(1)
)
"""

QUERY_APP_METRICS_ERRORS = """
SELECT error_type, count() AS count, max(timestamp) AS last_seen
FROM app_metrics
WHERE team_id = %(team_id)s
  AND plugin_config_id = %(plugin_config_id)s
  {category_clause}
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
  AND error_type = %(error_type)s
  {category_clause}
  {job_id_clause}
ORDER BY timestamp DESC
LIMIT 20
"""
