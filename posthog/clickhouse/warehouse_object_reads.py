from enum import StrEnum

from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed

WAREHOUSE_OBJECT_READS_DAILY_TABLE = "warehouse_object_reads_daily"
SHARDED_WAREHOUSE_OBJECT_READS_DAILY_TABLE = f"sharded_{WAREHOUSE_OBJECT_READS_DAILY_TABLE}"
SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE = f"{SHARDED_WAREHOUSE_OBJECT_READS_DAILY_TABLE}_staging"
WAREHOUSE_OBJECT_READS_RETENTION_DAYS = 60


class ReadKind(StrEnum):
    READ = "read"
    REFRESH = "refresh"


class SubjectKind(StrEnum):
    SAVED_QUERY = "saved_query"
    TABLE = "table"


def _enum8_type(values: type[StrEnum]) -> str:
    members = ", ".join(f"'{member.value}' = {position}" for position, member in enumerate(values, start=1))
    return f"Enum8({members})"


DIMENSION_COLUMNS = (
    "workflow_id",
    "lc_kind",
    "lc_product",
    "lc_feature",
    "lc_access_method",
    "source",
    "scene",
    "has_user_id",
    "read_alone",
)

SORT_KEY_COLUMNS = ("team_id", "day", "read_kind", "subject_kind", "subject_id", *DIMENSION_COLUMNS)

_COLUMNS = f"""
    team_id Int64,
    day Date,
    read_kind {_enum8_type(ReadKind)},
    subject_kind {_enum8_type(SubjectKind)},
    subject_id String,
    workflow_id String,
    lc_kind LowCardinality(String),
    lc_product LowCardinality(String),
    lc_feature LowCardinality(String),
    lc_access_method LowCardinality(String),
    source LowCardinality(String),
    scene LowCardinality(String),
    has_user_id Bool,
    read_alone Bool,
    requests AggregateFunction(uniq, String),
    users AggregateFunction(uniq, Int64),
    read_count SimpleAggregateFunction(sum, UInt64),
    duration_ms_sum SimpleAggregateFunction(sum, UInt64),
    read_bytes_sum SimpleAggregateFunction(sum, UInt64),
    duration_ms_quantiles AggregateFunction(quantiles(0.5, 0.9), UInt64),
    read_bytes_quantiles AggregateFunction(quantiles(0.5, 0.9), UInt64),
    max_event_time SimpleAggregateFunction(max, DateTime)"""


def _storage_table_sql(create_clause: str, table_name: str, engine: AggregatingMergeTree) -> str:
    return f"""
{create_clause} {table_name}
({_COLUMNS}
) ENGINE = {engine}
PARTITION BY toYYYYMMDD(day)
ORDER BY ({", ".join(SORT_KEY_COLUMNS)})
TTL day + INTERVAL {WAREHOUSE_OBJECT_READS_RETENTION_DAYS} DAY
SETTINGS ttl_only_drop_parts = 1
"""


def SHARDED_WAREHOUSE_OBJECT_READS_DAILY_TABLE_SQL() -> str:
    return _storage_table_sql(
        "CREATE TABLE IF NOT EXISTS",
        SHARDED_WAREHOUSE_OBJECT_READS_DAILY_TABLE,
        AggregatingMergeTree(WAREHOUSE_OBJECT_READS_DAILY_TABLE),
    )


def SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE_SQL() -> str:
    return _storage_table_sql(
        "CREATE TABLE IF NOT EXISTS",
        SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE,
        AggregatingMergeTree(SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE),
    )


def REPLACE_SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE_SQL() -> str:
    return _storage_table_sql(
        "CREATE OR REPLACE TABLE",
        SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE,
        AggregatingMergeTree(SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE, force_unique_zk_path=True),
    )


def DISTRIBUTED_WAREHOUSE_OBJECT_READS_DAILY_TABLE_SQL() -> str:
    engine = Distributed(data_table=SHARDED_WAREHOUSE_OBJECT_READS_DAILY_TABLE, cluster=settings.CLICKHOUSE_AUX_CLUSTER)
    return f"""
CREATE TABLE IF NOT EXISTS {WAREHOUSE_OBJECT_READS_DAILY_TABLE}
({_COLUMNS}
) ENGINE = {engine}
"""


def TRUNCATE_WAREHOUSE_OBJECT_READS_DAILY_TABLES_SQL() -> list[str]:
    return [
        f"TRUNCATE TABLE IF EXISTS {table_name}"
        for table_name in (
            SHARDED_WAREHOUSE_OBJECT_READS_DAILY_TABLE,
            SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE,
        )
    ]
