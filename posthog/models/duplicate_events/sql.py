from django.conf import settings

from posthog.clickhouse.indexes import index_by_kafka_timestamp
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION, kafka_engine
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine

DUPLICATE_EVENTS_TABLE = "duplicate_events"
DUPLICATE_EVENTS_WRITABLE_TABLE = f"writable_{DUPLICATE_EVENTS_TABLE}"
KAFKA_DUPLICATE_EVENTS_TABLE = f"kafka_{DUPLICATE_EVENTS_TABLE}"
DUPLICATE_EVENTS_MV = f"{DUPLICATE_EVENTS_TABLE}_mv"

# Base SQL for main data table and writable distributed table
DUPLICATE_EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    distinct_id String,
    event String,
    source_uuid UUID,
    duplicate_uuid UUID,
    similarity_score Float64,
    dedup_type LowCardinality(String),  -- "timestamp" or "uuid"
    is_confirmed UInt8,
    reason Nullable(String),
    version String,
    different_property_count UInt32,
    properties_similarity Float64,
    source_message String,  -- JSON string of full event
    duplicate_message String,  -- JSON string of full event
    distinct_fields Array(Tuple(field_name String, original_value String, new_value String)),
    inserted_at DateTime64(3, 'UTC')
    {extra_fields}
) ENGINE = {engine}
"""

# Kafka table uses String for distinct_fields since it receives JSON
KAFKA_DUPLICATE_EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    distinct_id String,
    event String,
    source_uuid UUID,
    duplicate_uuid UUID,
    similarity_score Float64,
    dedup_type LowCardinality(String),
    is_confirmed UInt8,
    reason Nullable(String),
    version String,
    different_property_count UInt32,
    properties_similarity Float64,
    source_message String,
    duplicate_message String,
    distinct_fields String,  -- JSON array as string from Kafka
    inserted_at DateTime64(3, 'UTC')
) ENGINE = {engine}
"""


def DUPLICATE_EVENTS_TABLE_ENGINE():
    return MergeTreeEngine(DUPLICATE_EVENTS_TABLE)


def DUPLICATE_EVENTS_TABLE_SQL():
    return (
        DUPLICATE_EVENTS_TABLE_BASE_SQL
        + """
    PARTITION BY toYYYYMMDD(inserted_at)
    ORDER BY (team_id, distinct_id, event, inserted_at)
    TTL inserted_at + INTERVAL 7 DAY DELETE
    SETTINGS index_granularity = 512
    """
    ).format(
        table_name=DUPLICATE_EVENTS_TABLE,
        engine=DUPLICATE_EVENTS_TABLE_ENGINE(),
        extra_fields=f"""
    {KAFKA_COLUMNS_WITH_PARTITION}
    , {index_by_kafka_timestamp(DUPLICATE_EVENTS_TABLE)}
    """,
    )


def DUPLICATE_EVENTS_WRITABLE_TABLE_SQL():
    return DUPLICATE_EVENTS_TABLE_BASE_SQL.format(
        table_name=DUPLICATE_EVENTS_WRITABLE_TABLE,
        engine=Distributed(
            data_table=DUPLICATE_EVENTS_TABLE,
            cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER,
        ),
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
    )


def KAFKA_DUPLICATE_EVENTS_TABLE_SQL():
    return KAFKA_DUPLICATE_EVENTS_TABLE_BASE_SQL.format(
        table_name=KAFKA_DUPLICATE_EVENTS_TABLE,
        engine=kafka_engine(topic="clickhouse_ingestion_events_duplicates", group="clickhouse_duplicate_events"),
    )


def DUPLICATE_EVENTS_MV_SQL(target_table=DUPLICATE_EVENTS_WRITABLE_TABLE):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
TO {target_table}
AS SELECT
team_id,
distinct_id,
event,
source_uuid,
duplicate_uuid,
similarity_score,
dedup_type,
is_confirmed,
reason,
version,
different_property_count,
properties_similarity,
source_message,
duplicate_message,
JSONExtract(distinct_fields, 'Array(Tuple(field_name String, original_value String, new_value String))') as distinct_fields,
inserted_at,
_timestamp,
_offset,
_partition
FROM {database}.{kafka_table}
""".format(
        mv_name=DUPLICATE_EVENTS_MV,
        target_table=target_table,
        kafka_table=KAFKA_DUPLICATE_EVENTS_TABLE,
        database=settings.CLICKHOUSE_DATABASE,
    )


def DROP_DUPLICATE_EVENTS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DUPLICATE_EVENTS_TABLE} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"


def DROP_DUPLICATE_EVENTS_WRITABLE_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DUPLICATE_EVENTS_WRITABLE_TABLE} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"


def DROP_KAFKA_DUPLICATE_EVENTS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {KAFKA_DUPLICATE_EVENTS_TABLE} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"


def DROP_DUPLICATE_EVENTS_MV_SQL():
    return f"DROP TABLE IF EXISTS {DUPLICATE_EVENTS_MV} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"


def TRUNCATE_DUPLICATE_EVENTS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {DUPLICATE_EVENTS_TABLE} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
