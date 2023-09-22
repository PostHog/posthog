from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS, kafka_engine, ttl_period
from posthog.clickhouse.table_engines import ReplacingMergeTree
from posthog.kafka_client.topics import KAFKA_LOG_ENTRIES
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

LOG_ENTRIES_TABLE = "log_entries"
LOG_ENTRIES_TTL_WEEKS = 1

LOG_ENTRIES_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    team_id UInt64,
    log_source LowCardinality(String),
    log_source_id VARCHAR,
    instance_id VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    level LowCardinality(String),
    message VARCHAR
    {extra_fields}
) ENGINE = {engine}
"""

LOG_ENTRIES_TABLE_ENGINE = lambda: ReplacingMergeTree(LOG_ENTRIES_TABLE, ver="_timestamp")
LOG_ENTRIES_TABLE_SQL = lambda: (
    LOG_ENTRIES_TABLE_BASE_SQL
    + """ORDER BY (team_id, log_source, log_source_id, instance_id, timestamp)
{ttl_period}
SETTINGS index_granularity=512
"""
).format(
    table_name=LOG_ENTRIES_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    extra_fields=KAFKA_COLUMNS,
    engine=LOG_ENTRIES_TABLE_ENGINE(),
    ttl_period=ttl_period("timestamp", LOG_ENTRIES_TTL_WEEKS),
)

KAFKA_LOG_ENTRIES_TABLE_SQL = lambda: LOG_ENTRIES_TABLE_BASE_SQL.format(
    table_name="kafka_" + LOG_ENTRIES_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    engine=kafka_engine(topic=KAFKA_LOG_ENTRIES),
    extra_fields="",
)

LOG_ENTRIES_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS {table_name}_mv ON CLUSTER '{cluster}'
TO {database}.{table_name}
AS SELECT
team_id,
log_source,
log_source_id,
instance_id,
timestamp,
level,
message,
_timestamp,
_offset
FROM {database}.kafka_{table_name}
""".format(
    table_name=LOG_ENTRIES_TABLE, cluster=CLICKHOUSE_CLUSTER, database=CLICKHOUSE_DATABASE
)


INSERT_LOG_ENTRY_SQL = """
INSERT INTO log_entries SELECT %(team_id)s, %(log_source)s, %(log_source_id)s, %(instance_id)s, %(timestamp)s, %(level)s, %(message)s, now(), 0
"""

TRUNCATE_LOG_ENTRIES_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {LOG_ENTRIES_TABLE} ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
