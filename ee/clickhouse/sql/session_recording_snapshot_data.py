from django.conf import settings

from ee.clickhouse.sql.clickhouse import KAFKA_COLUMNS, kafka_engine, ttl_period
from ee.clickhouse.sql.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from ee.kafka_client.topics import KAFKA_SESSION_RECORDING_SNAPSHOT_DATA

SESSION_RECORDING_SNAPSHOT_DATA_DATA_TABLE = (
    lambda: "sharded_session_recording_snapshot_data"
    if settings.CLICKHOUSE_REPLICATION
    else "session_recording_snapshot_data"
)

SESSION_RECORDING_SNAPSHOT_DATA_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    uuid UUID,
    timestamp DateTime64(6, 'UTC'),
    session_id VARCHAR,
    window_id VARCHAR,
    snapshot_data VARCHAR  -- no trailing comma, extra_fields leads with one
    {extra_fields}
) ENGINE = {engine}
"""

SESSION_RECORDING_SNAPSHOT_DATA_DATA_TABLE_ENGINE = lambda: ReplacingMergeTree(
    "session_recording_snapshot_data", ver="_timestamp", replication_scheme=ReplicationScheme.SHARDED
)
SESSION_RECORDING_SNAPSHOT_DATA_TABLE_SQL = lambda: (
    SESSION_RECORDING_SNAPSHOT_DATA_TABLE_BASE_SQL
    + """PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (toHour(timestamp), session_id, timestamp, uuid)
{ttl_period}
SETTINGS index_granularity=512
"""
).format(
    table_name=SESSION_RECORDING_SNAPSHOT_DATA_DATA_TABLE(),
    cluster=settings.CLICKHOUSE_CLUSTER,
    extra_fields=KAFKA_COLUMNS,
    engine=SESSION_RECORDING_SNAPSHOT_DATA_DATA_TABLE_ENGINE(),
    ttl_period=ttl_period("timestamp"),
)

KAFKA_SESSION_RECORDING_SNAPSHOT_DATA_TABLE_SQL = lambda: SESSION_RECORDING_SNAPSHOT_DATA_TABLE_BASE_SQL.format(
    table_name="kafka_session_recording_snapshot_data",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=kafka_engine(topic=KAFKA_SESSION_RECORDING_SNAPSHOT_DATA),
    materialized_columns="",
    extra_fields="",
)


# Distributed engine tables are only created if CLICKHOUSE_REPLICATED

# This table is responsible for writing to sharded_session_recording_snapshot_data based on a sharding key.
WRITABLE_SESSION_RECORDING_SNAPSHOT_DATA_TABLE_SQL = lambda: SESSION_RECORDING_SNAPSHOT_DATA_TABLE_BASE_SQL.format(
    table_name="writable_session_recording_snapshot_data",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(data_table=SESSION_RECORDING_SNAPSHOT_DATA_DATA_TABLE(), sharding_key="sipHash64(session_id)"),
    extra_fields=KAFKA_COLUMNS,
    materialized_columns="",
)

# This table is responsible for reading from session_recording_events on a cluster setting
DISTRIBUTED_SESSION_RECORDING_SNAPSHOT_DATA_TABLE_SQL = lambda: SESSION_RECORDING_SNAPSHOT_DATA_TABLE_BASE_SQL.format(
    table_name="session_recording_snapshot_data",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(data_table=SESSION_RECORDING_SNAPSHOT_DATA_DATA_TABLE(), sharding_key="sipHash64(session_id)"),
    extra_fields=KAFKA_COLUMNS,
)
