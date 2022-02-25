from ee.kafka_client.topics import KAFKA_SESSION_RECORDING_EVENTS
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

from .clickhouse import KAFKA_COLUMNS, ReplicationScheme, TableEngine, kafka_engine, table_engine, ttl_period

SESSION_RECORDING_EVENTS_TABLE = "session_recording_events"

SESSION_RECORDING_EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER {cluster}
(
    uuid UUID,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    session_id VARCHAR,
    window_id VARCHAR,
    snapshot_data VARCHAR,
    created_at DateTime64(6, 'UTC')
    {materialized_columns}
    {extra_fields}
) ENGINE = {engine}
"""

SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMNS = """
    , has_full_snapshot BOOLEAN materialized JSONExtractBool(snapshot_data, 'has_full_snapshot')
"""

SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMN_COMMENTS_SQL = """
    ALTER TABLE {table_name}
    ON CLUSTER {cluster}
    COMMENT COLUMN has_full_snapshot 'column_materializer::has_full_snapshot'
""".format(
    table_name=SESSION_RECORDING_EVENTS_TABLE, cluster=CLICKHOUSE_CLUSTER,
)

SESSION_RECORDING_EVENTS_TABLE_SQL = lambda: (
    SESSION_RECORDING_EVENTS_TABLE_BASE_SQL
    + """PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (team_id, toHour(timestamp), session_id, timestamp, uuid)
{ttl_period}
SETTINGS index_granularity=512
"""
).format(
    table_name=SESSION_RECORDING_EVENTS_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    materialized_columns=SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMNS,
    extra_fields=KAFKA_COLUMNS,
    # :TODO: Note that this is out of sync with proper setup on sharded setups.
    engine=table_engine(
        SESSION_RECORDING_EVENTS_TABLE, "_timestamp", TableEngine.ReplacingMergeTree, ReplicationScheme.SHARDED
    ),
    ttl_period=ttl_period(),
)

KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL = lambda: SESSION_RECORDING_EVENTS_TABLE_BASE_SQL.format(
    table_name="kafka_" + SESSION_RECORDING_EVENTS_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    engine=kafka_engine(topic=KAFKA_SESSION_RECORDING_EVENTS),
    materialized_columns="",
    extra_fields="",
)

SESSION_RECORDING_EVENTS_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW {table_name}_mv ON CLUSTER {cluster}
TO {database}.{table_name}
AS SELECT
uuid,
timestamp,
team_id,
distinct_id,
session_id,
window_id,
snapshot_data,
created_at,
_timestamp,
_offset
FROM {database}.kafka_{table_name}
""".format(
    table_name=SESSION_RECORDING_EVENTS_TABLE, cluster=CLICKHOUSE_CLUSTER, database=CLICKHOUSE_DATABASE,
)


INSERT_SESSION_RECORDING_EVENT_SQL = """
INSERT INTO session_recording_events (uuid, timestamp, team_id, distinct_id, session_id, window_id, snapshot_data, created_at, _timestamp, _offset)
SELECT %(uuid)s, %(timestamp)s, %(team_id)s, %(distinct_id)s, %(session_id)s, %(window_id)s, %(snapshot_data)s, %(created_at)s, now(), 0
"""


TRUNCATE_SESSION_RECORDING_EVENTS_TABLE_SQL = (
    f"TRUNCATE TABLE IF EXISTS {SESSION_RECORDING_EVENTS_TABLE} ON CLUSTER {CLICKHOUSE_CLUSTER}"
)

DROP_SESSION_RECORDING_EVENTS_TABLE_SQL = (
    f"DROP TABLE IF EXISTS {SESSION_RECORDING_EVENTS_TABLE} ON CLUSTER {CLICKHOUSE_CLUSTER}"
)

UPDATE_RECORDINGS_TABLE_TTL_SQL = (
    "ALTER TABLE session_recording_events MODIFY TTL toDate(created_at) + toIntervalWeek(%(weeks)s)"
)
