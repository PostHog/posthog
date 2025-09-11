from django.conf import settings

from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.indexes import index_by_kafka_timestamp
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS, kafka_engine, ttl_period
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS

SESSION_RECORDING_EVENTS_DATA_TABLE = lambda: "sharded_session_recording_events"

SESSION_RECORDING_EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
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

MATERIALIZED_COLUMNS = {
    "has_full_snapshot": {
        "schema": "Int8",
        "materializer": "MATERIALIZED JSONExtractBool(snapshot_data, 'has_full_snapshot')",
    },
    "events_summary": {
        "schema": "Array(String)",
        "materializer": "MATERIALIZED JSONExtract(JSON_QUERY(snapshot_data, '$.events_summary[*]'), 'Array(String)')",
    },
    "click_count": {
        "schema": "Int8",
        "materializer": "MATERIALIZED length(arrayFilter((x) -> JSONExtractInt(x, 'type') = 3 AND JSONExtractInt(x, 'data', 'source') = 2, events_summary))",
    },
    "keypress_count": {
        "schema": "Int8",
        "materializer": "MATERIALIZED length(arrayFilter((x) -> JSONExtractInt(x, 'type') = 3 AND JSONExtractInt(x, 'data', 'source') = 5, events_summary))",
    },
    "timestamps_summary": {
        "schema": "Array(DateTime64(6, 'UTC'))",
        "materializer": "MATERIALIZED arraySort(arrayMap((x) -> toDateTime(JSONExtractInt(x, 'timestamp') / 1000), events_summary))",
    },
    "first_event_timestamp": {
        "schema": "Nullable(DateTime64(6, 'UTC'))",
        "materializer": "MATERIALIZED if(empty(timestamps_summary), NULL, arrayReduce('min', timestamps_summary))",
    },
    "last_event_timestamp": {
        "schema": "Nullable(DateTime64(6, 'UTC'))",
        "materializer": "MATERIALIZED if(empty(timestamps_summary), NULL, arrayReduce('max', timestamps_summary))",
    },
    "urls": {
        "schema": "Array(String)",
        "materializer": "MATERIALIZED arrayFilter(x -> x != '', arrayMap((x) -> JSONExtractString(x, 'data', 'href'), events_summary))",
    },
}


# Like "has_full_snapshot Int8 MATERIALIZED JSONExtractBool(snapshot_data, 'has_full_snapshot') COMMENT 'column_materializer::has_full_snapshot'"
SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMNS = ", " + ", ".join(
    f"{column_name} {column['schema']} {column['materializer']}" for column_name, column in MATERIALIZED_COLUMNS.items()
)

# Like "has_full_snapshot Int8 COMMENT 'column_materializer::has_full_snapshot'"
SESSION_RECORDING_EVENTS_PROXY_MATERIALIZED_COLUMNS = ", " + ", ".join(
    f"{column_name} {column['schema']} COMMENT 'column_materializer::{column_name}'"
    for column_name, column in MATERIALIZED_COLUMNS.items()
)


SESSION_RECORDING_EVENTS_DATA_TABLE_ENGINE = lambda: ReplacingMergeTree(
    "session_recording_events",
    ver="_timestamp",
    replication_scheme=ReplicationScheme.SHARDED,
)
SESSION_RECORDING_EVENTS_TABLE_SQL = lambda on_cluster=True: (
    SESSION_RECORDING_EVENTS_TABLE_BASE_SQL
    + """PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (team_id, toHour(timestamp), session_id, timestamp, uuid)
{ttl_period}
SETTINGS index_granularity=512
"""
).format(
    table_name=SESSION_RECORDING_EVENTS_DATA_TABLE(),
    on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    materialized_columns=SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMNS,
    extra_fields=f"""
    {KAFKA_COLUMNS}
    , {index_by_kafka_timestamp(SESSION_RECORDING_EVENTS_DATA_TABLE())}
    """,
    engine=SESSION_RECORDING_EVENTS_DATA_TABLE_ENGINE(),
    ttl_period=ttl_period(),
)

KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL = lambda on_cluster=True: SESSION_RECORDING_EVENTS_TABLE_BASE_SQL.format(
    table_name="kafka_session_recording_events",
    on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    engine=kafka_engine(topic=KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS),
    materialized_columns="",
    extra_fields="",
)

SESSION_RECORDING_EVENTS_TABLE_MV_SQL = (
    lambda: """
CREATE MATERIALIZED VIEW IF NOT EXISTS session_recording_events_mv {on_cluster_clause}
TO {database}.{target_table}
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
FROM {database}.kafka_session_recording_events
""".format(
        target_table="writable_session_recording_events",
        on_cluster_clause=ON_CLUSTER_CLAUSE(),
        database=settings.CLICKHOUSE_DATABASE,
    )
)


# Distributed engine tables are only created if CLICKHOUSE_REPLICATED

# This table is responsible for writing to sharded_session_recording_events based on a sharding key.
WRITABLE_SESSION_RECORDING_EVENTS_TABLE_SQL = lambda on_cluster=True: SESSION_RECORDING_EVENTS_TABLE_BASE_SQL.format(
    table_name="writable_session_recording_events",
    on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    engine=Distributed(
        data_table=SESSION_RECORDING_EVENTS_DATA_TABLE(),
        sharding_key="sipHash64(distinct_id)",
    ),
    extra_fields=KAFKA_COLUMNS,
    materialized_columns="",
)

# This table is responsible for reading from session_recording_events on a cluster setting
DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL = lambda on_cluster=True: SESSION_RECORDING_EVENTS_TABLE_BASE_SQL.format(
    table_name="session_recording_events",
    on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    engine=Distributed(
        data_table=SESSION_RECORDING_EVENTS_DATA_TABLE(),
        sharding_key="sipHash64(distinct_id)",
    ),
    extra_fields=KAFKA_COLUMNS,
    materialized_columns=SESSION_RECORDING_EVENTS_PROXY_MATERIALIZED_COLUMNS,
)


INSERT_SESSION_RECORDING_EVENT_SQL = (
    lambda: f"""
INSERT INTO {SESSION_RECORDING_EVENTS_DATA_TABLE()} (uuid, timestamp, team_id, distinct_id, session_id, window_id, snapshot_data, created_at, _timestamp, _offset)
SELECT %(uuid)s, %(timestamp)s, %(team_id)s, %(distinct_id)s, %(session_id)s, %(window_id)s, %(snapshot_data)s, %(created_at)s, now(), 0
"""
)


TRUNCATE_SESSION_RECORDING_EVENTS_TABLE_SQL = lambda: (
    f"TRUNCATE TABLE IF EXISTS {SESSION_RECORDING_EVENTS_DATA_TABLE()} {ON_CLUSTER_CLAUSE()}"
)

DROP_SESSION_RECORDING_EVENTS_TABLE_SQL = lambda: (
    f"DROP TABLE IF EXISTS {SESSION_RECORDING_EVENTS_DATA_TABLE()} {ON_CLUSTER_CLAUSE()}"
)

UPDATE_RECORDINGS_TABLE_TTL_SQL = lambda: (
    f"ALTER TABLE {SESSION_RECORDING_EVENTS_DATA_TABLE()} {ON_CLUSTER_CLAUSE()} MODIFY TTL toDate(created_at) + toIntervalWeek(%(weeks)s)"
)
