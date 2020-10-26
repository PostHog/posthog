from .clickhouse import KAFKA_COLUMNS, STORAGE_POLICY, kafka_engine, table_engine

SESSION_RECORDING_EVENTS_TABLE = "session_recording_events"

SESSION_RECORDING_EVENTS_TABLE_SQL = """
CREATE TABLE {table_name}
(
    uuid UUID,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    session_id VARCHAR,
    snapshot_data VARCHAR,
    created_at DateTime64(6, 'UTC')
    {extra_fields}
) ENGINE = {engine}
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, session_id, uuid)
SAMPLE BY uuid
""".format(
    table_name=SESSION_RECORDING_EVENTS_TABLE,
    extra_fields=KAFKA_COLUMNS,
    engine=table_engine(SESSION_RECORDING_EVENTS_TABLE, "_timestamp"),
)

INSERT_SESSION_RECORDING_EVENT_SQL = """
INSERT INTO session_recording_events SELECT %(uuid)s, %(timestamp)s, %(team_id)s, %(distinct_id)s, %(session_id)s, %(snapshot_data)s, %(created_at)s, now(), 0
"""
