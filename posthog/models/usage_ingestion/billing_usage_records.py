from django.conf import settings

from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_BILLING_USAGE_RECORDS,
    KAFKA_COLUMNS_WITH_PARTITION,
    kafka_engine,
)
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_BILLING_USAGE_RECORDS

BILLING_USAGE_RECORDS_TABLE = "billing_usage_records"
SHARDED_BILLING_USAGE_RECORDS_TABLE = f"sharded_{BILLING_USAGE_RECORDS_TABLE}"
WRITABLE_BILLING_USAGE_RECORDS_TABLE = f"writable_{BILLING_USAGE_RECORDS_TABLE}"
KAFKA_BILLING_USAGE_RECORDS_TABLE = f"kafka_{BILLING_USAGE_RECORDS_TABLE}"
BILLING_USAGE_RECORDS_MV = f"{BILLING_USAGE_RECORDS_TABLE}_mv"


# Producers stamp event_timestamp when they flush, so the same record_id re-sent after a
# retry or a consumer replay carries a later timestamp. It therefore cannot be part of the
# identity, or every resend would bill again. inserted_at is the version column: the latest
# send of a record_id wins, which is also how a producer corrects a quantity.
# ponytail: collapse is still partition-scoped, so a replay that crosses a month boundary
# leaves both rows. Bounded by replays being operational events, not routine ones.
def billing_usage_records_data_table_engine() -> ReplacingMergeTree:
    return ReplacingMergeTree(
        SHARDED_BILLING_USAGE_RECORDS_TABLE,
        replication_scheme=ReplicationScheme.SHARDED,
        ver="inserted_at",
    )


# dimensions sits outside the sort key, so two sends of one identity collapse to whichever
# inserted last: a producer's dimensions have to be a function of its record_id.
BASE_BILLING_USAGE_RECORDS_COLUMNS = """
    schema_version UInt8,
    record_id String,
    producer_id LowCardinality(String),
    team_id Int64,
    organization_id UUID,
    usage_key LowCardinality(String),
    mode Enum8('delta' = 1, 'snapshot' = 2),
    unit LowCardinality(String),
    quantity Int64,
    event_timestamp DateTime64(6, 'UTC'),
    inserted_at DateTime64(6, 'UTC'),
    dimensions Map(LowCardinality(String), String)
""".strip()


def BILLING_USAGE_RECORDS_DATA_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {SHARDED_BILLING_USAGE_RECORDS_TABLE}
(
    {BASE_BILLING_USAGE_RECORDS_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
    , INDEX event_timestamp_minmax event_timestamp TYPE minmax GRANULARITY 3
)
ENGINE = {billing_usage_records_data_table_engine()}
PARTITION BY toYYYYMM(event_timestamp)
ORDER BY (team_id, producer_id, usage_key, record_id)
"""


def DISTRIBUTED_BILLING_USAGE_RECORDS_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {BILLING_USAGE_RECORDS_TABLE}
(
    {BASE_BILLING_USAGE_RECORDS_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {Distributed(data_table=SHARDED_BILLING_USAGE_RECORDS_TABLE, sharding_key="cityHash64(team_id)")}
"""


def WRITABLE_BILLING_USAGE_RECORDS_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {WRITABLE_BILLING_USAGE_RECORDS_TABLE}
(
    {BASE_BILLING_USAGE_RECORDS_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {Distributed(data_table=SHARDED_BILLING_USAGE_RECORDS_TABLE, sharding_key="cityHash64(team_id)")}
"""


def KAFKA_BILLING_USAGE_RECORDS_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {KAFKA_BILLING_USAGE_RECORDS_TABLE}
(
    {BASE_BILLING_USAGE_RECORDS_COLUMNS}
)
ENGINE = {
        kafka_engine(
            topic=KAFKA_BILLING_USAGE_RECORDS,
            group=CONSUMER_GROUP_BILLING_USAGE_RECORDS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_SHARED_NAMED_COLLECTION,
        )
    }
SETTINGS date_time_input_format = 'best_effort'
"""


def BILLING_USAGE_RECORDS_MV_SQL(target_table: str = WRITABLE_BILLING_USAGE_RECORDS_TABLE) -> str:
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {BILLING_USAGE_RECORDS_MV}
TO {target_table}
AS SELECT
    schema_version,
    record_id,
    producer_id,
    team_id,
    organization_id,
    usage_key,
    mode,
    unit,
    quantity,
    event_timestamp,
    inserted_at,
    dimensions,
    _timestamp,
    _offset,
    _partition
FROM {KAFKA_BILLING_USAGE_RECORDS_TABLE}
"""
