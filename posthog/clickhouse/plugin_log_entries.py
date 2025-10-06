from posthog import settings
from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS, kafka_engine, ttl_period
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree
from posthog.kafka_client.topics import KAFKA_PLUGIN_LOG_ENTRIES

PLUGIN_LOG_ENTRIES_TABLE = "plugin_log_entries"
PLUGIN_LOG_ENTRIES_TABLE_MV = f"{PLUGIN_LOG_ENTRIES_TABLE}_mv"
PLUGIN_LOG_ENTRIES_WRITABLE_TABLE = f"writable_{PLUGIN_LOG_ENTRIES_TABLE}"
KAFKA_PLUGIN_LOG_ENTRIES_TABLE = f"kafka_{PLUGIN_LOG_ENTRIES_TABLE}"

DROP_KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL = f"DROP TABLE IF EXISTS {KAFKA_PLUGIN_LOG_ENTRIES_TABLE}"
DROP_PLUGIN_LOG_ENTRIES_TABLE_MV_SQL = f"DROP TABLE IF EXISTS {PLUGIN_LOG_ENTRIES_TABLE_MV}"

PLUGIN_LOG_ENTRIES_TTL_WEEKS = 1

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


def PLUGIN_LOG_ENTRIES_TABLE_ENGINE():
    return ReplacingMergeTree(PLUGIN_LOG_ENTRIES_TABLE, ver="_timestamp")


def PLUGIN_LOG_ENTRIES_TABLE_SQL(on_cluster=True):
    return (
        PLUGIN_LOG_ENTRIES_TABLE_BASE_SQL
        + """PARTITION BY toYYYYMMDD(timestamp) ORDER BY (team_id, plugin_id, plugin_config_id, timestamp)
{ttl_period}
SETTINGS index_granularity=512
"""
    ).format(
        table_name=PLUGIN_LOG_ENTRIES_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        extra_fields=KAFKA_COLUMNS,
        engine=PLUGIN_LOG_ENTRIES_TABLE_ENGINE(),
        ttl_period=ttl_period("timestamp", PLUGIN_LOG_ENTRIES_TTL_WEEKS),
    )


def KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL(on_cluster=True):
    return PLUGIN_LOG_ENTRIES_TABLE_BASE_SQL.format(
        table_name=KAFKA_PLUGIN_LOG_ENTRIES_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(topic=KAFKA_PLUGIN_LOG_ENTRIES),
        extra_fields="",
    )


def PLUGIN_LOG_ENTRIES_TABLE_MV_SQL(on_cluster=True, target_table=PLUGIN_LOG_ENTRIES_WRITABLE_TABLE):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} {on_cluster_clause}
TO {target_table}
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
FROM {kafka_table}
""".format(
        target_table=target_table,
        mv_name=PLUGIN_LOG_ENTRIES_TABLE_MV,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        kafka_table=KAFKA_PLUGIN_LOG_ENTRIES_TABLE,
    )


def PLUGIN_LOG_ENTRIES_WRITABLE_TABLE_SQL():
    return PLUGIN_LOG_ENTRIES_TABLE_BASE_SQL.format(
        table_name=PLUGIN_LOG_ENTRIES_WRITABLE_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=Distributed(data_table=PLUGIN_LOG_ENTRIES_TABLE, cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER),
        extra_fields=KAFKA_COLUMNS,
    )


INSERT_PLUGIN_LOG_ENTRY_SQL = """
INSERT INTO plugin_log_entries SELECT %(id)s, %(team_id)s, %(plugin_id)s, %(plugin_config_id)s, %(timestamp)s, %(source)s, %(type)s, %(message)s, %(instance_id)s, now(), 0
"""

TRUNCATE_PLUGIN_LOG_ENTRIES_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {PLUGIN_LOG_ENTRIES_TABLE} {ON_CLUSTER_CLAUSE()}"
