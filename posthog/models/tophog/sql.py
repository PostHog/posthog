from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_TOPHOG, kafka_engine
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_TOPHOG

TABLE_BASE_NAME = "tophog"
DATA_TABLE_NAME = f"sharded_{TABLE_BASE_NAME}"


def TRUNCATE_TOPHOG_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {DATA_TABLE_NAME}"


KAFKA_TABLE_NAME = f"kafka_{TABLE_BASE_NAME}"

KAFKA_TOPHOG_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    timestamp DateTime64(6, 'UTC'),
    metric LowCardinality(String),
    type LowCardinality(String),
    key Map(LowCardinality(String), String),
    value Float64,
    count UInt64,
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
