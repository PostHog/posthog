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

BILLING_USAGE_RECORDS_DAILY_TABLE = "billing_usage_records_daily"
SHARDED_BILLING_USAGE_RECORDS_DAILY_TABLE = f"sharded_{BILLING_USAGE_RECORDS_DAILY_TABLE}"


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


def billing_usage_records_daily_data_table_engine(
    table_name: str = SHARDED_BILLING_USAGE_RECORDS_DAILY_TABLE,
) -> ReplacingMergeTree:
    return ReplacingMergeTree(
        table_name,
        replication_scheme=ReplicationScheme.SHARDED,
        ver="rolled_up_at",
    )


# Every producer stamps `timestamp` from its own clock when it flushes, never from anything a
# customer sends, which is what lets toDate(timestamp) sit in the sorting key. Sourcing it from
# event data would hand a customer control over whether their records deduplicate.
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


BILLING_USAGE_RECORDS_DAILY_COLUMNS = """
    day Date,
    team_id Int64,
    organization_id UUID,
    producer_id LowCardinality(String),
    usage_key LowCardinality(String),
    unit LowCardinality(String),
    quantity Int64,
    rolled_up_at DateTime64(6, 'UTC')
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
ENGINE = {Distributed(data_table=SHARDED_BILLING_USAGE_RECORDS_TABLE, sharding_key="cityHash64(team_id)")}
"""


def BILLING_USAGE_RECORDS_DAILY_DATA_TABLE_SQL(
    table_name: str = SHARDED_BILLING_USAGE_RECORDS_DAILY_TABLE,
) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {table_name}
(
    {BILLING_USAGE_RECORDS_DAILY_COLUMNS}
)
ENGINE = {billing_usage_records_daily_data_table_engine(table_name)}
PARTITION BY toYYYYMM(day)
ORDER BY (team_id, day, organization_id, producer_id, usage_key, unit)
""".strip()


def DISTRIBUTED_BILLING_USAGE_RECORDS_DAILY_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {BILLING_USAGE_RECORDS_DAILY_TABLE}
(
    {BILLING_USAGE_RECORDS_DAILY_COLUMNS}
)
ENGINE = {Distributed(data_table=SHARDED_BILLING_USAGE_RECORDS_DAILY_TABLE, sharding_key="cityHash64(team_id)")}
""".strip()


def BILLING_USAGE_RECORDS_DAILY_ROLLUP_SQL(
    source_table: str = BILLING_USAGE_RECORDS_TABLE,
    target_table: str = BILLING_USAGE_RECORDS_DAILY_TABLE,
) -> str:
    """Roll one complete UTC day into a replaceable daily snapshot.

    FINAL is safe here because the replacement key includes toDate(timestamp).
    Do not reuse this query for a rolling window.
    """
    return f"""
INSERT INTO {target_table}
SELECT
    toDate(timestamp) AS day,
    team_id,
    organization_id,
    producer_id,
    usage_key,
    unit,
    sum(quantity) AS quantity,
    %(rolled_up_at)s AS rolled_up_at
FROM {source_table} FINAL
WHERE timestamp >= %(day_start)s
  AND timestamp < %(day_end)s
GROUP BY day, team_id, organization_id, producer_id, usage_key, unit
SETTINGS do_not_merge_across_partitions_select_final = 1
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
    unit,
    quantity,
    timestamp,
    inserted_at,
    _timestamp,
    _offset,
    _partition
FROM {KAFKA_BILLING_USAGE_RECORDS_TABLE}
"""
