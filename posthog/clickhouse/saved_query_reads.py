from enum import StrEnum

from posthog.clickhouse.table_engines import AggregatingMergeTree

SAVED_QUERY_READS_DAILY_TABLE = "saved_query_reads_daily"
SAVED_QUERY_READS_DAILY_STAGING_TABLE = "saved_query_reads_daily_staging"
SAVED_QUERY_READS_RETENTION_DAYS = 60


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
    "names_only_this_subject",
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
    names_only_this_subject Bool,
    requests AggregateFunction(uniq, String),
    users AggregateFunction(uniq, Int64),
    read_count SimpleAggregateFunction(sum, UInt64),
    duration_ms_sum SimpleAggregateFunction(sum, UInt64),
    read_bytes_sum SimpleAggregateFunction(sum, UInt64),
    duration_ms_quantiles AggregateFunction(quantiles(0.5, 0.9), UInt64),
    read_bytes_quantiles AggregateFunction(quantiles(0.5, 0.9), UInt64),
    max_event_time SimpleAggregateFunction(max, DateTime)"""


def _saved_query_reads_table_sql(create_clause: str, table_name: str, force_unique_zk_path: bool = False) -> str:
    return f"""
{create_clause} {table_name}
({_COLUMNS}
) ENGINE = {AggregatingMergeTree(table_name, force_unique_zk_path=force_unique_zk_path)}
PARTITION BY toYYYYMMDD(day)
ORDER BY ({", ".join(SORT_KEY_COLUMNS)})
TTL day + INTERVAL {SAVED_QUERY_READS_RETENTION_DAYS} DAY
SETTINGS ttl_only_drop_parts = 1
"""


def SAVED_QUERY_READS_DAILY_TABLE_SQL() -> str:
    return _saved_query_reads_table_sql("CREATE TABLE IF NOT EXISTS", SAVED_QUERY_READS_DAILY_TABLE)


def SAVED_QUERY_READS_DAILY_STAGING_TABLE_SQL() -> str:
    return _saved_query_reads_table_sql("CREATE TABLE IF NOT EXISTS", SAVED_QUERY_READS_DAILY_STAGING_TABLE)


def REPLACE_SAVED_QUERY_READS_DAILY_STAGING_TABLE_SQL() -> str:
    return _saved_query_reads_table_sql(
        "CREATE OR REPLACE TABLE", SAVED_QUERY_READS_DAILY_STAGING_TABLE, force_unique_zk_path=True
    )


def TRUNCATE_SAVED_QUERY_READS_DAILY_TABLES_SQL() -> list[str]:
    return [
        f"TRUNCATE TABLE IF EXISTS {table_name}"
        for table_name in (SAVED_QUERY_READS_DAILY_TABLE, SAVED_QUERY_READS_DAILY_STAGING_TABLE)
    ]
