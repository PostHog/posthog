from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed

ENDPOINT_RUNS_HOURLY_TABLE = "endpoint_runs_hourly"
SHARDED_ENDPOINT_RUNS_HOURLY_TABLE = f"sharded_{ENDPOINT_RUNS_HOURLY_TABLE}"
SHARDED_ENDPOINT_RUNS_HOURLY_STAGING_TABLE = f"{SHARDED_ENDPOINT_RUNS_HOURLY_TABLE}_staging"
ENDPOINT_RUNS_RETENTION_DAYS = 60

SORT_KEY_COLUMNS = (
    "team_id",
    "day",
    "hour",
    "endpoint_id",
    "version",
    "execution_type",
    "access",
    "refresh_mode",
    "has_variables",
    "has_pagination",
)

# Bit i of active_slots is set when a run started in minutes [5i, 5i + 5) of the hour.
_COLUMNS = """
    team_id Int64,
    day Date,
    hour DateTime,
    endpoint_id String,
    version UInt32,
    execution_type LowCardinality(String),
    access LowCardinality(String),
    refresh_mode LowCardinality(String),
    has_variables Bool,
    has_pagination Bool,
    runs SimpleAggregateFunction(sum, UInt64),
    cache_hits SimpleAggregateFunction(sum, UInt64),
    cache_misses SimpleAggregateFunction(sum, UInt64),
    failed SimpleAggregateFunction(sum, UInt64),
    first_run_at SimpleAggregateFunction(min, DateTime),
    last_run_at SimpleAggregateFunction(max, DateTime),
    active_slots SimpleAggregateFunction(groupBitOr, UInt16),
    wait_ms_sum SimpleAggregateFunction(sum, UInt64),
    miss_wait_ms_sum SimpleAggregateFunction(sum, UInt64),
    miss_wait_ms_quantiles AggregateFunction(quantiles(0.5, 0.9), UInt64),
    ch_queries SimpleAggregateFunction(sum, UInt64),
    ch_duration_ms_sum SimpleAggregateFunction(sum, UInt64),
    ch_read_bytes_sum SimpleAggregateFunction(sum, UInt64),
    ch_cpu_us_sum SimpleAggregateFunction(sum, UInt64),
    ch_duration_ms_quantiles AggregateFunction(quantiles(0.5, 0.9), UInt64),
    ch_read_bytes_quantiles AggregateFunction(quantiles(0.5, 0.9), UInt64)"""


def _storage_table_sql(create_clause: str, table_name: str, engine: AggregatingMergeTree) -> str:
    return f"""
{create_clause} {table_name}
({_COLUMNS}
) ENGINE = {engine}
PARTITION BY toYYYYMMDD(day)
ORDER BY ({", ".join(SORT_KEY_COLUMNS)})
TTL day + INTERVAL {ENDPOINT_RUNS_RETENTION_DAYS} DAY
SETTINGS ttl_only_drop_parts = 1
"""


def SHARDED_ENDPOINT_RUNS_HOURLY_TABLE_SQL() -> str:
    return _storage_table_sql(
        "CREATE TABLE IF NOT EXISTS",
        SHARDED_ENDPOINT_RUNS_HOURLY_TABLE,
        AggregatingMergeTree(ENDPOINT_RUNS_HOURLY_TABLE),
    )


def SHARDED_ENDPOINT_RUNS_HOURLY_STAGING_TABLE_SQL() -> str:
    return _storage_table_sql(
        "CREATE TABLE IF NOT EXISTS",
        SHARDED_ENDPOINT_RUNS_HOURLY_STAGING_TABLE,
        AggregatingMergeTree(SHARDED_ENDPOINT_RUNS_HOURLY_STAGING_TABLE),
    )


def REPLACE_SHARDED_ENDPOINT_RUNS_HOURLY_STAGING_TABLE_SQL() -> str:
    return _storage_table_sql(
        "CREATE OR REPLACE TABLE",
        SHARDED_ENDPOINT_RUNS_HOURLY_STAGING_TABLE,
        AggregatingMergeTree(SHARDED_ENDPOINT_RUNS_HOURLY_STAGING_TABLE, force_unique_zk_path=True),
    )


def DISTRIBUTED_ENDPOINT_RUNS_HOURLY_TABLE_SQL() -> str:
    engine = Distributed(data_table=SHARDED_ENDPOINT_RUNS_HOURLY_TABLE, cluster=settings.CLICKHOUSE_AUX_CLUSTER)
    return f"""
CREATE TABLE IF NOT EXISTS {ENDPOINT_RUNS_HOURLY_TABLE}
({_COLUMNS}
) ENGINE = {engine}
"""


def TRUNCATE_ENDPOINT_RUNS_HOURLY_TABLES_SQL() -> list[str]:
    return [
        f"TRUNCATE TABLE IF EXISTS {table_name}"
        for table_name in (
            SHARDED_ENDPOINT_RUNS_HOURLY_TABLE,
            SHARDED_ENDPOINT_RUNS_HOURLY_STAGING_TABLE,
        )
    ]
