from ee.kafka_client.topics import KAFKA_PLUGIN_LOG_ENTRIES

from .clickhouse import KAFKA_COLUMNS, kafka_engine, table_engine, ttl_period

PLUGIN_LOG_ENTRIES_TABLE = "plugin_log_entries"

PLUGIN_LOG_ENTRIES_TABLE_BASE_SQL = """
CREATE TABLE {table_name}
(
    id UUID,
    team_id Int64,
    plugin_id Int64,
    timestamp DateTime64(6, 'UTC'),
    type VARCHAR,
    message VARCHAR,
    instance_id UUID
    {extra_fields}
) ENGINE = {engine}
"""

PLUGIN_LOG_ENTRIES_TABLE_SQL = (
    PLUGIN_LOG_ENTRIES_TABLE_BASE_SQL
    + """PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (team_id, toHour(timestamp), plugin_id, timestamp, id)
{ttl_period}
SETTINGS index_granularity=512
"""
).format(
    table_name=PLUGIN_LOG_ENTRIES_TABLE,
    extra_fields=KAFKA_COLUMNS,
    engine=table_engine(PLUGIN_LOG_ENTRIES_TABLE, "_timestamp"),
    ttl_period=ttl_period(),
)

KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL = PLUGIN_LOG_ENTRIES_TABLE_BASE_SQL.format(
    table_name="kafka_" + PLUGIN_LOG_ENTRIES_TABLE,
    engine=kafka_engine(topic=KAFKA_PLUGIN_LOG_ENTRIES),
    extra_fields="",
)

PLUGIN_LOG_ENTRIES_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW {table_name}_mv
TO {table_name}
AS SELECT
id,
team_id,
plugin_id,
timestamp,
type,
message,
instance_id,
_timestamp,
_offset
FROM kafka_{table_name}
""".format(
    table_name=PLUGIN_LOG_ENTRIES_TABLE
)


INSERT_PLUGIN_LOG_ENTRY_SQL = """
INSERT INTO plugin_log_entries SELECT %(id)s, %(team_id)s, %(plugin_id)s, %(timestamp)s, %(type)s, %(message)s, %(instance_id)s, now(), 0
"""

DROP_PLUGIN_LOG_ENTRIES_TABLE_SQL = "DROP TABLE plugin_log_entries"
