from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_TOPHOG, kafka_engine, ttl_period
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_TOPHOG

TOPHOG_TTL_DAYS = 30

TABLE_BASE_NAME = "tophog"
DATA_TABLE_NAME = f"sharded_{TABLE_BASE_NAME}"
WRITABLE_TABLE_NAME = f"writable_{TABLE_BASE_NAME}"
KAFKA_TABLE_NAME = f"kafka_{TABLE_BASE_NAME}"
MV_NAME = f"{TABLE_BASE_NAME}_mv"


def TOPHOG_DATA_TABLE_ENGINE():
    return MergeTreeEngine(
        TABLE_BASE_NAME,
        replication_scheme=ReplicationScheme.SHARDED,
    )


TOPHOG_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    timestamp DateTime64(6, 'UTC'),
    metric LowCardinality(String),
    key Map(LowCardinality(String), String),
    value Float64,
    pipeline LowCardinality(String),
    lane LowCardinality(String),
    labels Map(LowCardinality(String), String)
) ENGINE = {engine}
"""


def TOPHOG_DATA_TABLE_SQL():
    return (
        TOPHOG_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (pipeline, lane, metric, timestamp, key)
{ttl}
SETTINGS ttl_only_drop_parts = 1
"""
    ).format(
        table_name=DATA_TABLE_NAME,
        engine=TOPHOG_DATA_TABLE_ENGINE(),
        ttl=ttl_period("timestamp", TOPHOG_TTL_DAYS, unit="DAY"),
    )


def WRITABLE_TOPHOG_TABLE_SQL():
    return TOPHOG_TABLE_BASE_SQL.format(
        table_name=WRITABLE_TABLE_NAME,
        engine=Distributed(
            data_table=DATA_TABLE_NAME,
            sharding_key="sipHash64(toString(key))",
        ),
    )


def DISTRIBUTED_TOPHOG_TABLE_SQL():
    return TOPHOG_TABLE_BASE_SQL.format(
        table_name=TABLE_BASE_NAME,
        engine=Distributed(
            data_table=DATA_TABLE_NAME,
            sharding_key="sipHash64(toString(key))",
        ),
    )


KAFKA_TOPHOG_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    timestamp DateTime64(6, 'UTC'),
    metric LowCardinality(String),
    key Map(LowCardinality(String), String),
    value Float64,
    pipeline LowCardinality(String),
    lane LowCardinality(String),
    labels Map(LowCardinality(String), String)
) ENGINE = {engine}
SETTINGS date_time_input_format = 'best_effort', kafka_skip_broken_messages = 100
"""


def KAFKA_TOPHOG_TABLE_SQL():
    return KAFKA_TOPHOG_TABLE_BASE_SQL.format(
        table_name=KAFKA_TABLE_NAME,
        engine=kafka_engine(topic=KAFKA_CLICKHOUSE_TOPHOG, group=CONSUMER_GROUP_TOPHOG),
    )


def TOPHOG_MV_SQL(target_table: str = WRITABLE_TABLE_NAME):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
TO {target_table}
AS SELECT
    timestamp,
    metric,
    key,
    value,
    pipeline,
    lane,
    labels
FROM {kafka_table}
""".format(
        mv_name=MV_NAME,
        target_table=target_table,
        kafka_table=KAFKA_TABLE_NAME,
    )


def TRUNCATE_TOPHOG_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {DATA_TABLE_NAME}"
