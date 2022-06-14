from django.conf import settings

from ee.kafka_client.topics import KAFKA_SESSION_RECORDING_METADATA
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS, kafka_engine
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

SESSION_RECORDING_METADATA_DATA_TABLE = "sharded_session_recording_metadata"

SESSION_RECORDING_METADATA_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    team_id Int64,
    distinct_id VARCHAR,
    session_id VARCHAR,
    window_id VARCHAR,
    session_start DateTime64(6, 'UTC'),
    session_end DateTime64(6, 'UTC'),
    duration Int64,
    snapshot_data_location VARCHAR
    {extra_fields}
) ENGINE = {engine}
"""

SESSION_RECORDING_METADATA_DATA_TABLE_ENGINE = lambda: ReplacingMergeTree(
    "session_recording_metadata", ver="_timestamp", replication_scheme=ReplicationScheme.SHARDED
)
SESSION_RECORDING_METADATA_TABLE_SQL = lambda: (
    SESSION_RECORDING_METADATA_TABLE_BASE_SQL
    + """PARTITION BY toYYYYMMDD(session_end)
ORDER BY (team_id, session_id, session_start, session_end)
"""
).format(
    table_name=SESSION_RECORDING_METADATA_DATA_TABLE,
    cluster=settings.CLICKHOUSE_CLUSTER,
    extra_fields=KAFKA_COLUMNS,
    engine=SESSION_RECORDING_METADATA_DATA_TABLE_ENGINE(),
)

KAFKA_SESSION_RECORDING_METADATA_TABLE_SQL = lambda: SESSION_RECORDING_METADATA_TABLE_BASE_SQL.format(
    table_name="kafka_session_recording_metadata",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=kafka_engine(topic=KAFKA_SESSION_RECORDING_METADATA),
    materialized_columns="",
    extra_fields="",
)

SESSION_RECORDING_METADATA_TABLE_MV_SQL = lambda: """
CREATE MATERIALIZED VIEW session_recording_metadata_mv ON CLUSTER '{cluster}'
TO {database}.{target_table}
AS SELECT
team_id,
distinct_id,
session_id,
window_id,
session_start,
session_end,
duration,
snapshot_data_location
_timestamp,
_offset
FROM {database}.kafka_session_recording_metadata
""".format(
    target_table=("writable_session_recording_metadata"),
    cluster=settings.CLICKHOUSE_CLUSTER,
    database=settings.CLICKHOUSE_DATABASE,
)

# This table is responsible for writing to sharded_session_recording_metadata based on a sharding key.
WRITABLE_SESSION_RECORDING_METADATA_TABLE_SQL = lambda: SESSION_RECORDING_METADATA_TABLE_BASE_SQL.format(
    table_name="writable_session_recording_metadata",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(data_table=SESSION_RECORDING_METADATA_DATA_TABLE, sharding_key="sipHash64(session_id)"),
    extra_fields=KAFKA_COLUMNS,
    materialized_columns="",
)

# This table is responsible for reading from session_recording_events on a cluster setting
DISTRIBUTED_SESSION_RECORDING_METADATA_TABLE_SQL = lambda: SESSION_RECORDING_METADATA_TABLE_BASE_SQL.format(
    table_name="session_recording_metadata",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(data_table=SESSION_RECORDING_METADATA_DATA_TABLE, sharding_key="sipHash64(session_id)"),
    extra_fields=KAFKA_COLUMNS,
)
