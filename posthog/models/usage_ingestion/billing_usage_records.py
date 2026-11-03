from django.conf import settings

from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_BILLING_USAGE_RECORDS,
    KAFKA_COLUMNS_WITH_PARTITION,
    kafka_engine,
)
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_BILLING_USAGE_RECORDS
from posthog.run_mode import run_mode

BILLING_USAGE_RECORDS_TABLE = "billing_usage_records"
SHARDED_BILLING_USAGE_RECORDS_TABLE = f"sharded_{BILLING_USAGE_RECORDS_TABLE}"
WRITABLE_BILLING_USAGE_RECORDS_TABLE = f"writable_{BILLING_USAGE_RECORDS_TABLE}"
KAFKA_BILLING_USAGE_RECORDS_TABLE = f"kafka_{BILLING_USAGE_RECORDS_TABLE}"
BILLING_USAGE_RECORDS_MV = f"{BILLING_USAGE_RECORDS_TABLE}_mv"


# inserted_at is the version column, so the latest send of an identity wins, which is also
# how a producer corrects a quantity. It is deliberately absent from the HogQL schema:
# `timestamp` is monotonic per resend, so argMax on it reads what a merge would keep, and
# exposing two time columns invites filtering on the one that is not in the sorting key.
def billing_usage_records_data_table_engine() -> ReplacingMergeTree:
    return ReplacingMergeTree(
        SHARDED_BILLING_USAGE_RECORDS_TABLE,
        replication_scheme=ReplicationScheme.SHARDED,
        ver="inserted_at",
    )


# Event-derived producers use trusted server capture time when available; aggregate producers use
# their emission clock. Never use customer-supplied timestamps, which would let a customer control
# whether their records deduplicate.
BASE_BILLING_USAGE_RECORDS_COLUMNS = """
    schema_version UInt8,
    record_id String,
    producer_id LowCardinality(String),
    team_id Int64,
    organization_id UUID,
    usage_key LowCardinality(String),
    unit LowCardinality(String),
    quantity Int64,
    timestamp DateTime64(6, 'UTC'),
    inserted_at DateTime64(6, 'UTC')
""".strip()


def BILLING_USAGE_RECORDS_DATA_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {SHARDED_BILLING_USAGE_RECORDS_TABLE}
(
    {BASE_BILLING_USAGE_RECORDS_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {billing_usage_records_data_table_engine()}
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), producer_id, usage_key, record_id)
"""


SHARDED_BILLING_USAGE_RECORDS_V2_TABLE = f"{SHARDED_BILLING_USAGE_RECORDS_TABLE}_v2"
BILLING_USAGE_RECORDS_HOT_DAYS = 30


def billing_usage_records_v2_data_table_engine() -> ReplacingMergeTree:
    return ReplacingMergeTree(
        SHARDED_BILLING_USAGE_RECORDS_V2_TABLE,
        replication_scheme=ReplicationScheme.SHARDED,
        ver="inserted_at",
    )


def _billing_usage_records_v2_tiering() -> str:
    # The s3_tiered policy and its `cold` volume exist only on deployed-cloud clusters.
    if run_mode().is_deployed_cloud:
        return (
            f"TTL toDate(timestamp) + INTERVAL {BILLING_USAGE_RECORDS_HOT_DAYS} DAY TO VOLUME 'cold'\n"
            "SETTINGS storage_policy = 's3_tiered'"
        )
    return ""


# The sorting key holds the same columns as the v1 table, so both tables deduplicate the same rows.
# The day leads the key because every reader filters on a time range, and a team-first key forces
# a one-day read to scan the whole month of every small team. Each usage key has one producer, so
# usage_key before producer_id lets a filter on a few keys skip granules without changing the order.
def BILLING_USAGE_RECORDS_V2_DATA_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {SHARDED_BILLING_USAGE_RECORDS_V2_TABLE}
(
    {BASE_BILLING_USAGE_RECORDS_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {billing_usage_records_v2_data_table_engine()}
PARTITION BY toYYYYMM(timestamp)
ORDER BY (toDate(timestamp), team_id, usage_key, producer_id, record_id)
{_billing_usage_records_v2_tiering()}
"""


def DISTRIBUTED_BILLING_USAGE_RECORDS_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {BILLING_USAGE_RECORDS_TABLE}
(
    {BASE_BILLING_USAGE_RECORDS_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {
        Distributed(
            data_table=SHARDED_BILLING_USAGE_RECORDS_TABLE,
            sharding_key="cityHash64(team_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        )
    }
"""


def WRITABLE_BILLING_USAGE_RECORDS_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {WRITABLE_BILLING_USAGE_RECORDS_TABLE}
(
    {BASE_BILLING_USAGE_RECORDS_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {
        Distributed(
            data_table=SHARDED_BILLING_USAGE_RECORDS_TABLE,
            sharding_key="cityHash64(team_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        )
    }
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
    unit,
    quantity,
    timestamp,
    inserted_at,
    _timestamp,
    _offset,
    _partition
FROM {KAFKA_BILLING_USAGE_RECORDS_TABLE}
"""
