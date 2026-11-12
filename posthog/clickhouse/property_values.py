from django.conf import settings

from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_PROPERTY_VALUES,
    CONSUMER_GROUP_PROPERTY_VALUES_DAILY,
    kafka_engine,
    kafka_num_consumers,
)
from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_PROPERTY_VALUES

TABLE_NAME = "property_values"
KAFKA_TABLE_NAME = f"kafka_{TABLE_NAME}"
MV_NAME = f"{TABLE_NAME}_mv"
DISTRIBUTED_TABLE_NAME = f"{TABLE_NAME}_distributed"

DAILY_TABLE_NAME = "property_values_daily"
KAFKA_DAILY_TABLE_NAME = f"kafka_{DAILY_TABLE_NAME}"
DAILY_MV_NAME = f"{DAILY_TABLE_NAME}_mv"
DISTRIBUTED_DAILY_TABLE_NAME = f"{DAILY_TABLE_NAME}_distributed"

# The Kafka message schema: pre-processed rows from the property-values aggregator.
# Each message is one (team_id, property_type, property_key, property_value)
# tuple plus an accumulated `property_count` from the aggregator's flush window.
KAFKA_PROPERTY_VALUES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    `team_id` Int64,
    `property_type` LowCardinality(String),
    `property_key` String,
    `property_value` String,
    `property_count` UInt64
) ENGINE = {engine}
SETTINGS kafka_num_consumers = {num_consumers}, kafka_thread_per_consumer = 1
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
    index_granularity = 8192
"""
    ).format(
        table_name=TABLE_NAME,
        engine=AggregatingMergeTree(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED),
        extra_fields=""",
    INDEX idx_property_value_ngrambf lower(property_value) TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1""",
    )


def _kafka_property_values_table_sql(table_name: str, group: str) -> str:
    return KAFKA_PROPERTY_VALUES_TABLE_SQL.format(
        table_name=table_name,
        num_consumers=kafka_num_consumers(8),
        engine=kafka_engine(
            topic=KAFKA_CLICKHOUSE_PROPERTY_VALUES,
            group=group,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION,
        ),
    )


def KAFKA_PROPERTY_VALUES_TABLE_SQL_FN() -> str:
    return _kafka_property_values_table_sql(KAFKA_TABLE_NAME, CONSUMER_GROUP_PROPERTY_VALUES)


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
    property_count,
    coalesce(_timestamp, now()) as last_seen
FROM {database}.{kafka_table}
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


PROPERTY_VALUES_DAILY_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    `team_id` Int64,
    `property_type` LowCardinality(String),
    `property_key` LowCardinality(String),
    `property_value` String,
    `day` Date DEFAULT toDate(now())
) ENGINE = {engine}
"""


def PROPERTY_VALUES_DAILY_TABLE_SQL() -> str:
    return (
        PROPERTY_VALUES_DAILY_TABLE_BASE_SQL
        + """
PARTITION BY day
ORDER BY (team_id, property_type, property_key, property_value)
TTL day + INTERVAL 7 DAY DELETE
SETTINGS
    index_granularity = 8192,
    ttl_only_drop_parts = 1
"""
    ).format(
        table_name=DAILY_TABLE_NAME,
        engine=AggregatingMergeTree(DAILY_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED),
    )


def KAFKA_PROPERTY_VALUES_DAILY_TABLE_SQL() -> str:
    return _kafka_property_values_table_sql(KAFKA_DAILY_TABLE_NAME, CONSUMER_GROUP_PROPERTY_VALUES_DAILY)


def PROPERTY_VALUES_DAILY_MV_SQL() -> str:
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {DAILY_MV_NAME}
TO {DAILY_TABLE_NAME}
AS SELECT
    team_id,
    property_type,
    property_key,
    property_value,
    toDate(coalesce(_timestamp, now())) as day
FROM {settings.CLICKHOUSE_DATABASE}.{KAFKA_DAILY_TABLE_NAME}
"""


def DISTRIBUTED_PROPERTY_VALUES_DAILY_TABLE_SQL() -> str:
    return PROPERTY_VALUES_DAILY_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_DAILY_TABLE_NAME,
        engine=Distributed(
            data_table=DAILY_TABLE_NAME,
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )
