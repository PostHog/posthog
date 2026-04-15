from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_FEATURE_FLAG_CALL_DEBUG,
    KAFKA_COLUMNS_WITH_PARTITION,
    kafka_engine,
)
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_FEATURE_FLAG_CALL_DEBUG_JSON

TABLE_BASE_NAME = "feature_flag_call_debug"
DATA_TABLE_NAME = f"sharded_{TABLE_BASE_NAME}"
KAFKA_TABLE_NAME = f"kafka_{TABLE_BASE_NAME}_json"
MV_NAME = f"{TABLE_BASE_NAME}_json_mv"

SHARDING_KEY = "cityHash64(toString(team_id))"

# Kafka engine table — receives the standard RawKafkaEvent JSON format
KAFKA_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    uuid UUID,
    event VARCHAR,
    properties VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC'),
    person_id UUID,
    person_properties VARCHAR,
    person_created_at DateTime64,
    person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)
) ENGINE = {engine}
"""

# Data table — stores full original properties for debugging, with extracted columns for lookups
DATA_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    uuid UUID,
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    distinct_id String,
    person_id UUID,
    flag_key String,
    properties String CODEC(ZSTD(3)),
    drop_date Date MATERIALIZED toDate(timestamp) + toIntervalDay(365)

    {extra_fields}
    {indexes}
) ENGINE = {engine}
"""

INDEXES = """
    , INDEX idx_flag_key flag_key TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX idx_uuid uuid TYPE bloom_filter(0.001) GRANULARITY 1
"""


def DATA_TABLE_ENGINE():
    return MergeTreeEngine(
        TABLE_BASE_NAME,
        replication_scheme=ReplicationScheme.SHARDED,
    )


def DATA_TABLE_SQL():
    return (
        DATA_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMM(drop_date)
ORDER BY (team_id, flag_key, timestamp)
TTL drop_date
SETTINGS ttl_only_drop_parts = 1
"""
    ).format(
        table_name=DATA_TABLE_NAME,
        engine=DATA_TABLE_ENGINE(),
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
        indexes=INDEXES,
    )


def DISTRIBUTED_TABLE_SQL():
    return DATA_TABLE_BASE_SQL.format(
        table_name=TABLE_BASE_NAME,
        engine=Distributed(
            data_table=DATA_TABLE_NAME,
            sharding_key=SHARDING_KEY,
        ),
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
        indexes="",
    )


def KAFKA_TABLE_SQL():
    return KAFKA_TABLE_BASE_SQL.format(
        table_name=KAFKA_TABLE_NAME,
        engine=kafka_engine(
            topic=KAFKA_CLICKHOUSE_FEATURE_FLAG_CALL_DEBUG_JSON,
            group=CONSUMER_GROUP_FEATURE_FLAG_CALL_DEBUG,
        ),
    )


def MV_SQL(target_table: str = TABLE_BASE_NAME):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
TO {target_table}
AS SELECT
    uuid,
    team_id,
    timestamp,
    distinct_id,
    person_id,
    JSONExtractString(src.properties, '$feature_flag') AS flag_key,
    src.properties AS properties,
    _timestamp,
    _offset,
    _partition
FROM {kafka_table} AS src
""".format(
        mv_name=MV_NAME,
        target_table=target_table,
        kafka_table=KAFKA_TABLE_NAME,
    )


def TRUNCATE_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {DATA_TABLE_NAME}"
