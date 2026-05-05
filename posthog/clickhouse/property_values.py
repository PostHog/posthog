from django.conf import settings

from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_PROPERTY_VALUES, kafka_engine
from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_PROPERTY_VALUES

TABLE_NAME = "property_values"
KAFKA_TABLE_NAME = f"kafka_{TABLE_NAME}"
MV_NAME = f"{TABLE_NAME}_mv"
DISTRIBUTED_TABLE_NAME = f"{TABLE_NAME}_distributed"

# The Kafka message schema: pre-processed rows from the WarpStream pipeline.
# Each message is one (team_id, property_type, property_key, property_value) tuple.
KAFKA_PROPERTY_VALUES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    `team_id` Int64,
    `property_type` LowCardinality(String),
    `property_key` String,
    `property_value` String
) ENGINE = {engine}
"""

PROPERTY_VALUES_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    `team_id` Int64 CODEC(DoubleDelta, ZSTD(1)),
    `property_type` LowCardinality(String),
    `property_key` LowCardinality(String),
    `property_value` String,
    `property_count` SimpleAggregateFunction(sum, UInt64),
    `last_seen` SimpleAggregateFunction(max, DateTime) DEFAULT now()
    {extra_fields}
) ENGINE = {engine}
"""


def PROPERTY_VALUES_TABLE_SQL() -> str:
    return (
        PROPERTY_VALUES_TABLE_BASE_SQL
        + """
ORDER BY (team_id, property_type, property_key, property_value)
TTL last_seen + INTERVAL 30 DAY DELETE
SETTINGS
    index_granularity = 8192,
    enable_full_text_index = 1
"""
    ).format(
        table_name=TABLE_NAME,
        engine=AggregatingMergeTree(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED),
        extra_fields=""",
    INDEX idx_property_value property_value TYPE text(tokenizer = ngrams(3)) GRANULARITY 1""",
    )


def KAFKA_PROPERTY_VALUES_TABLE_SQL_FN() -> str:
    return KAFKA_PROPERTY_VALUES_TABLE_SQL.format(
        table_name=KAFKA_TABLE_NAME,
        engine=kafka_engine(
            topic=KAFKA_CLICKHOUSE_PROPERTY_VALUES,
            group=CONSUMER_GROUP_PROPERTY_VALUES,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION,
        ),
    )


def DROP_KAFKA_PROPERTY_VALUES_TABLE_SQL() -> str:
    return f"DROP TABLE IF EXISTS {KAFKA_TABLE_NAME}"


def DROP_PROPERTY_VALUES_MV_SQL() -> str:
    return f"DROP TABLE IF EXISTS {MV_NAME}"


def PROPERTY_VALUES_MV_SQL() -> str:
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
TO {table_name}
AS SELECT
    team_id,
    property_type,
    property_key,
    property_value,
    toUInt64(1) as property_count,
    coalesce(_timestamp, now()) as last_seen
FROM {database}.{kafka_table}
WHERE lengthUTF8(property_key) > 0
  AND lengthUTF8(property_key) <= 400  -- matches Django PropertyDefinition.name max_length
  AND lengthUTF8(property_value) > 0
  AND lengthUTF8(property_value) < 256
""".format(
        mv_name=MV_NAME,
        table_name=TABLE_NAME,
        kafka_table=KAFKA_TABLE_NAME,
        database=settings.CLICKHOUSE_DATABASE,
    )


def DISTRIBUTED_PROPERTY_VALUES_TABLE_SQL() -> str:
    return PROPERTY_VALUES_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_TABLE_NAME,
        engine=Distributed(
            data_table=TABLE_NAME,
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
        extra_fields="",
    )
