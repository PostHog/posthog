from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.kafka_client.topics import KAFKA_PLUGIN_LOG_ENTRIES

PLUGIN_LOG_ENTRIES_TABLE = "plugin_log_entries"


INSERT_PLUGIN_LOG_ENTRY_SQL = """
INSERT INTO plugin_log_entries SELECT %(id)s, %(team_id)s, %(plugin_id)s, %(plugin_config_id)s, %(timestamp)s, %(source)s, %(type)s, %(message)s, %(instance_id)s, now(), 0
"""

KAFKA_PLUGIN_LOG_ENTRIES_TABLE = f"kafka_{PLUGIN_LOG_ENTRIES_TABLE}"

PLUGIN_LOG_ENTRIES_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
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


def KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL(on_cluster=True):
    return PLUGIN_LOG_ENTRIES_TABLE_BASE_SQL.format(
        table_name=KAFKA_PLUGIN_LOG_ENTRIES_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(topic=KAFKA_PLUGIN_LOG_ENTRIES),
        extra_fields="",
    )
