from ee.clickhouse.sql.clickhouse import KAFKA_COLUMNS, kafka_engine, ttl_period
from ee.clickhouse.sql.table_engines import ReplacingMergeTree
from ee.kafka_client.topics import KAFKA_PLUGIN_LOG_ENTRIES
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE
from posthog.tasks.delete_old_plugin_logs import TTL_WEEKS

PLUGIN_LOG_ENTRIES_TABLE = "plugin_log_entries"

PLUGIN_LOG_ENTRIES_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    id UUID,
    team_id Int64,
    plugin_id Int64,
    plugin_config_id Int64,
    timestamp DateTime64(6, 'UTC'),
    source VARCHAR,
    type VARCHAR,
    message VARCHAR,
    instance_id UUID
    {extra_fields}
) ENGINE = {engine}
"""

PLUGIN_LOG_ENTRIES_TABLE_ENGINE = lambda: ReplacingMergeTree(PLUGIN_LOG_ENTRIES_TABLE, ver="_timestamp")
PLUGIN_LOG_ENTRIES_TABLE_SQL = lambda: (
    PLUGIN_LOG_ENTRIES_TABLE_BASE_SQL
    + """PARTITION BY plugin_id ORDER BY (team_id, id)
{ttl_period}
SETTINGS index_granularity=512
"""
).format(
    table_name=PLUGIN_LOG_ENTRIES_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    extra_fields=KAFKA_COLUMNS,
    engine=PLUGIN_LOG_ENTRIES_TABLE_ENGINE(),
    ttl_period=ttl_period("timestamp", TTL_WEEKS),
)

KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL = lambda: PLUGIN_LOG_ENTRIES_TABLE_BASE_SQL.format(
    table_name="kafka_" + PLUGIN_LOG_ENTRIES_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    engine=kafka_engine(topic=KAFKA_PLUGIN_LOG_ENTRIES),
    extra_fields="",
)

PLUGIN_LOG_ENTRIES_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW {table_name}_mv ON CLUSTER '{cluster}'
TO {database}.{table_name}
AS SELECT
id,
team_id,
plugin_id,
plugin_config_id,
timestamp,
source,
type,
message,
instance_id,
_timestamp,
_offset
FROM {database}.kafka_{table_name}
""".format(
    table_name=PLUGIN_LOG_ENTRIES_TABLE, cluster=CLICKHOUSE_CLUSTER, database=CLICKHOUSE_DATABASE,
)


INSERT_PLUGIN_LOG_ENTRY_SQL = """
INSERT INTO plugin_log_entries SELECT %(id)s, %(team_id)s, %(plugin_id)s, %(plugin_config_id)s, %(timestamp)s, %(source)s, %(type)s, %(message)s, %(instance_id)s, now(), 0
"""

TRUNCATE_PLUGIN_LOG_ENTRIES_TABLE_SQL = (
    f"TRUNCATE TABLE IF EXISTS {PLUGIN_LOG_ENTRIES_TABLE} ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
)
