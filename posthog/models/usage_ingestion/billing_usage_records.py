from django.conf import settings

from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_BILLING_USAGE_RECORDS,
    KAFKA_COLUMNS_WITH_PARTITION,
    kafka_engine,
    kafka_num_consumers,
)
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_BILLING_USAGE_RECORDS
from posthog.run_mode import RunMode, run_mode

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


# kafka_num_consumers is per node. One consumer reads its partitions in partition order, so when it
# falls behind, its last partition takes all of the lag. US runs two consumers on each node, with
# two partitions each. The other deployments keep one consumer, and their SQL does not change.
def billing_usage_records_consumer_settings() -> str:
    if run_mode() is not RunMode.CLOUD_US:
        return ""
    return f", kafka_num_consumers = {kafka_num_consumers(2)}, kafka_thread_per_consumer = 1"


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
SETTINGS date_time_input_format = 'best_effort'{billing_usage_records_consumer_settings()}
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
