from django.conf import settings

from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_USAGE_RECORDS, KAFKA_COLUMNS_WITH_PARTITION, kafka_engine
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_USAGE_RECORDS

USAGE_RECORDS_TABLE = "usage_records"
SHARDED_USAGE_RECORDS_TABLE = f"sharded_{USAGE_RECORDS_TABLE}"
WRITABLE_USAGE_RECORDS_TABLE = f"writable_{USAGE_RECORDS_TABLE}"
KAFKA_USAGE_RECORDS_TABLE = f"kafka_{USAGE_RECORDS_TABLE}"
USAGE_RECORDS_MV = f"{USAGE_RECORDS_TABLE}_mv"


def usage_records_data_table_engine() -> ReplacingMergeTree:
    return ReplacingMergeTree(
        SHARDED_USAGE_RECORDS_TABLE,
        replication_scheme=ReplicationScheme.SHARDED,
        ver="event_timestamp",
    )


BASE_USAGE_RECORDS_COLUMNS = """
    schema_version UInt8,
    record_id String,
    producer_id LowCardinality(String),
    team_id Int64,
    organization_id UUID,
    usage_key LowCardinality(String),
    mode Enum8('delta' = 1, 'snapshot' = 2),
    unit LowCardinality(String),
    quantity Int64,
    version UInt64,
    event_timestamp DateTime64(6, 'UTC'),
    inserted_at DateTime64(6, 'UTC'),
    source_ref String,
    user_id String,
    variant String,
    dimensions Map(LowCardinality(String), String)
""".strip()


def USAGE_RECORDS_DATA_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {SHARDED_USAGE_RECORDS_TABLE}
(
    {BASE_USAGE_RECORDS_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {usage_records_data_table_engine()}
PARTITION BY toYYYYMM(event_timestamp)
ORDER BY (team_id, producer_id, record_id, version)
"""


def DISTRIBUTED_USAGE_RECORDS_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {USAGE_RECORDS_TABLE}
(
    {BASE_USAGE_RECORDS_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {Distributed(data_table=SHARDED_USAGE_RECORDS_TABLE, sharding_key="sipHash64(team_id)")}
"""


def WRITABLE_USAGE_RECORDS_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {WRITABLE_USAGE_RECORDS_TABLE}
(
    {BASE_USAGE_RECORDS_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {Distributed(data_table=SHARDED_USAGE_RECORDS_TABLE, sharding_key="sipHash64(team_id)")}
"""


def KAFKA_USAGE_RECORDS_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {KAFKA_USAGE_RECORDS_TABLE}
(
    {BASE_USAGE_RECORDS_COLUMNS}
)
ENGINE = {
        kafka_engine(
            topic=KAFKA_USAGE_RECORDS,
            group=CONSUMER_GROUP_USAGE_RECORDS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_SHARED_NAMED_COLLECTION,
        )
    }
SETTINGS date_time_input_format = 'best_effort'
"""


def USAGE_RECORDS_MV_SQL(target_table: str = WRITABLE_USAGE_RECORDS_TABLE) -> str:
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {USAGE_RECORDS_MV}
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
    version,
    event_timestamp,
    inserted_at,
    source_ref,
    user_id,
    variant,
    dimensions,
    _timestamp,
    _offset,
    _partition
FROM {KAFKA_USAGE_RECORDS_TABLE}
"""
