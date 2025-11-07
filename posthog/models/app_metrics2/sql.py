from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION, kafka_engine, ttl_period
from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_APP_METRICS2

APP_METRICS2_TTL_DAYS = 90

APP_METRICS2_TABLE = "app_metrics2"
APP_METRICS2_SHARDED_TABLE = f"sharded_{APP_METRICS2_TABLE}"
APP_METRICS2_MV_TABLE = f"{APP_METRICS2_TABLE}_mv"
APP_METRICS2_WRITABLE_TABLE = f"writable_{APP_METRICS2_TABLE}"
KAFKA_APP_METRICS2_TABLE = f"kafka_{APP_METRICS2_TABLE}"

DROP_APP_METRICS2_MV_TABLE_SQL = f"DROP TABLE IF EXISTS {APP_METRICS2_MV_TABLE}"
DROP_KAFKA_APP_METRICS2_TABLE_SQL = f"DROP TABLE IF EXISTS {KAFKA_APP_METRICS2_TABLE}"


def APP_METRICS2_SHARDED_TABLE_ENGINE():
    return AggregatingMergeTree(APP_METRICS2_SHARDED_TABLE, replication_scheme=ReplicationScheme.SHARDED)


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
    metric_kind LowCardinality(String),
    metric_name LowCardinality(String),
    count SimpleAggregateFunction(sum, Int64)
""".strip()

# NOTE: We have producers that take advantage of the timestamp being truncated to the hour,
# i.e. they batch up metrics and send them pre-truncated. If we ever change this truncation
# we need to revisit producers (e.g. the webhook service currently known as rusty-hook or pgqueue).
APP_METRICS2_TIMESTAMP_TRUNCATION = "toStartOfHour(timestamp)"

APP_METRICS2_DATA_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS {APP_METRICS2_SHARDED_TABLE}
(
    {BASE_APP_METRICS2_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {APP_METRICS2_SHARDED_TABLE_ENGINE()}
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, app_source, app_source_id, instance_id, {APP_METRICS2_TIMESTAMP_TRUNCATION}, metric_kind, metric_name)
{ttl_period("timestamp", APP_METRICS2_TTL_DAYS, unit="DAY")}
"""
)

DISTRIBUTED_APP_METRICS2_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS {APP_METRICS2_TABLE}
(
    {BASE_APP_METRICS2_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE={Distributed(data_table=APP_METRICS2_SHARDED_TABLE, sharding_key="rand()")}
"""
)

WRITABLE_APP_METRICS2_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS {APP_METRICS2_WRITABLE_TABLE}
(
    {BASE_APP_METRICS2_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE={Distributed(data_table=APP_METRICS2_SHARDED_TABLE, sharding_key="rand()")}
"""
)

KAFKA_APP_METRICS2_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS {KAFKA_APP_METRICS2_TABLE}
(
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    app_source LowCardinality(String),
    app_source_id String,
    instance_id String,
    metric_kind String,
    metric_name String,
    count Int64
)
ENGINE={kafka_engine(topic=KAFKA_APP_METRICS2)}
"""
)

APP_METRICS2_MV_TABLE_SQL = (
    lambda target_table=APP_METRICS2_WRITABLE_TABLE: f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS app_metrics2_mv
TO {target_table}
AS SELECT
team_id,
timestamp,
app_source,
app_source_id,
instance_id,
metric_kind,
metric_name,
count,
_timestamp,
_offset,
_partition
FROM {KAFKA_APP_METRICS2_TABLE}
"""
)


TRUNCATE_APP_METRICS2_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {APP_METRICS2_SHARDED_TABLE}"

INSERT_APP_METRICS2_SQL = """
INSERT INTO sharded_app_metrics2 (
    team_id,
    timestamp,
    app_source,
    app_source_id,
    instance_id,
    metric_kind,
    metric_name,
    count,
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
    %(metric_kind)s,
    %(metric_name)s,
    %(count)s,
    now(),
    0,
    0
"""
