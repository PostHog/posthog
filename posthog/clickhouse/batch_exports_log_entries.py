from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS, kafka_engine, ttl_period
from posthog.clickhouse.table_engines import ReplacingMergeTree
from posthog.kafka_client.topics import KAFKA_BATCH_EXPORTS_LOG_ENTRIES
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

BATCH_EXPORTS_LOG_ENTRIES_TABLE = "batch_exports_log_entries"
BATCH_EXPORTS_LOG_ENTRIES_TTL_WEEKS = 1

BATCH_EXPORTS_LOG_ENTRIES_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    team_id UInt64,
    batch_export_id VARCHAR,
    run_id VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    level VARCHAR,
    message VARCHAR
    {extra_fields}
) ENGINE = {engine}
"""

BATCH_EXPORTS_LOG_ENTRIES_TABLE_ENGINE = lambda: ReplacingMergeTree(BATCH_EXPORTS_LOG_ENTRIES_TABLE, ver="_timestamp")
BATCH_EXPORTS_LOG_ENTRIES_TABLE_SQL = lambda: (
    BATCH_EXPORTS_LOG_ENTRIES_TABLE_BASE_SQL
    + """ORDER BY (team_id, batch_export_id, run_id, timestamp)
{ttl_period}
SETTINGS index_granularity=512
"""
).format(
    table_name=BATCH_EXPORTS_LOG_ENTRIES_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    extra_fields=KAFKA_COLUMNS,
    engine=BATCH_EXPORTS_LOG_ENTRIES_TABLE_ENGINE(),
    ttl_period=ttl_period("timestamp", BATCH_EXPORTS_LOG_ENTRIES_TTL_WEEKS),
)

KAFKA_BATCH_EXPORTS_LOG_ENTRIES_TABLE_SQL = lambda: BATCH_EXPORTS_LOG_ENTRIES_TABLE_BASE_SQL.format(
    table_name="kafka_" + BATCH_EXPORTS_LOG_ENTRIES_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    engine=kafka_engine(topic=KAFKA_BATCH_EXPORTS_LOG_ENTRIES),
    extra_fields="",
)

BATCH_EXPORTS_LOG_ENTRIES_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS {table_name}_mv ON CLUSTER '{cluster}'
TO {database}.{table_name}
AS SELECT
team_id,
batch_export_id,
run_id,
timestamp,
level,
message,
_timestamp,
_offset
FROM {database}.kafka_{table_name}
""".format(
    table_name=BATCH_EXPORTS_LOG_ENTRIES_TABLE, cluster=CLICKHOUSE_CLUSTER, database=CLICKHOUSE_DATABASE
)


INSERT_BATCH_EXPORTS_LOG_ENTRY_SQL = """
INSERT INTO batch_exports_log_entries SELECT %(team_id)s, %(batch_export_id)s, %(run_id)s, %(timestamp)s, %(level)s, %(message)s, now(), 0
"""

TRUNCATE_BATCH_EXPORTS_LOG_ENTRIES_TABLE_SQL = (
    f"TRUNCATE TABLE IF EXISTS {BATCH_EXPORTS_LOG_ENTRIES_TABLE} ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
)
