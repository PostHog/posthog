from django.conf import settings

from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_DISTINCT_ID_USAGE, kafka_engine, ttl_period
from posthog.clickhouse.table_engines import Distributed, ReplicationScheme, SummingMergeTree
from posthog.kafka_client.topics import KAFKA_DISTINCT_ID_USAGE_EVENTS_JSON

DISTINCT_ID_USAGE_TTL_DAYS = 7

TABLE_BASE_NAME = "distinct_id_usage"
DATA_TABLE_NAME = f"sharded_{TABLE_BASE_NAME}"
WRITABLE_TABLE_NAME = f"writable_{TABLE_BASE_NAME}"
KAFKA_TABLE_NAME = f"kafka_{TABLE_BASE_NAME}"
MV_NAME = f"{TABLE_BASE_NAME}_mv"


def DISTINCT_ID_USAGE_DATA_TABLE_ENGINE():
    return SummingMergeTree(
        TABLE_BASE_NAME,
        replication_scheme=ReplicationScheme.SHARDED,
        columns="(event_count)",
    )


DISTINCT_ID_USAGE_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    distinct_id String,
    minute DateTime,
    event_count UInt64
) ENGINE = {engine}
"""


def DISTINCT_ID_USAGE_DATA_TABLE_SQL():
    return (
        DISTINCT_ID_USAGE_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(minute)
ORDER BY (team_id, minute, distinct_id)
{ttl}
SETTINGS ttl_only_drop_parts = 1
"""
    ).format(
        table_name=DATA_TABLE_NAME,
        engine=DISTINCT_ID_USAGE_DATA_TABLE_ENGINE(),
        ttl=ttl_period("minute", DISTINCT_ID_USAGE_TTL_DAYS, unit="DAY"),
    )


def WRITABLE_DISTINCT_ID_USAGE_TABLE_SQL():
    return DISTINCT_ID_USAGE_TABLE_BASE_SQL.format(
        table_name=WRITABLE_TABLE_NAME,
        engine=Distributed(
            data_table=DATA_TABLE_NAME,
            sharding_key="sipHash64(distinct_id)",
        ),
    )


def DISTRIBUTED_DISTINCT_ID_USAGE_TABLE_SQL():
    return DISTINCT_ID_USAGE_TABLE_BASE_SQL.format(
        table_name=TABLE_BASE_NAME,
        engine=Distributed(
            data_table=DATA_TABLE_NAME,
            sharding_key="sipHash64(distinct_id)",
        ),
    )


# Kafka table - reads from the distinct_id_usage_events_json topic
# This topic is populated by a WarpStream pipeline that extracts only the fields we need
# We add settings to prevent poison pills from stopping ingestion
# kafka_skip_broken_messages is an int so we set it to skip all broken messages
KAFKA_DISTINCT_ID_USAGE_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    distinct_id VARCHAR,
    timestamp DateTime64(6, 'UTC')
) ENGINE = {engine}
SETTINGS kafka_skip_broken_messages = 100
"""


def KAFKA_DISTINCT_ID_USAGE_TABLE_SQL():
    return KAFKA_DISTINCT_ID_USAGE_TABLE_BASE_SQL.format(
        table_name=KAFKA_TABLE_NAME,
        engine=kafka_engine(
            topic=KAFKA_DISTINCT_ID_USAGE_EVENTS_JSON,
            group=CONSUMER_GROUP_DISTINCT_ID_USAGE,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_NAMED_COLLECTION,
        ),
    )


def DISTINCT_ID_USAGE_MV_SQL(target_table: str = WRITABLE_TABLE_NAME):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
TO {target_table}
AS SELECT
    team_id,
    distinct_id,
    toStartOfMinute(timestamp) AS minute,
    1 AS event_count
FROM {kafka_table}
""".format(
        mv_name=MV_NAME,
        target_table=target_table,
        kafka_table=KAFKA_TABLE_NAME,
    )


def TRUNCATE_DISTINCT_ID_USAGE_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {DATA_TABLE_NAME}"
