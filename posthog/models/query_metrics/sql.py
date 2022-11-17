# Note: These tables are not (yet) created automatically, as they're considered experimental on cloud and exact schema is in flux.

from posthog.clickhouse.dictionaries import dictionary_source_clickhouse
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION, kafka_engine
from posthog.clickhouse.table_engines import MergeTreeEngine
from posthog.kafka_client.topics import KAFKA_METRICS_TIME_TO_SEE_DATA
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

CREATE_TEAM_EVENTS_LAST_MONTH_VIEW = (
    lambda: f"""
CREATE VIEW team_events_last_month_view ON CLUSTER '{CLICKHOUSE_CLUSTER}' AS
SELECT team_id, count() AS event_count
FROM events
WHERE timestamp > now() - toIntervalMonth(1) AND timestamp < now()
GROUP BY team_id
ORDER BY event_count DESC
"""
)

DROP_TEAM_EVENTS_LAST_MONTH_VIEW = "DROP TABLE team_events_last_month_view ON CLUSTER '{CLICKHOUSE_CLUSTER}'"

CREATE_TEAM_EVENTS_LAST_MONTH_DICTIONARY = (
    lambda: f"""
CREATE DICTIONARY IF NOT EXISTS {CLICKHOUSE_DATABASE}.team_events_last_month_dictionary ON CLUSTER '{CLICKHOUSE_CLUSTER}'
(
    team_id UInt64,
    event_count UInt64
)
PRIMARY KEY team_id
{dictionary_source_clickhouse(table='team_events_last_month_view')}
LAYOUT(complex_key_cache(size_in_cells 100000))
Lifetime(86400)
"""
)

DROP_TEAM_EVENTS_LAST_MONTH_DICTIONARY = (
    "DROP DICTIONARY team_events_last_month_dictionary ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
)

METRICS_TIME_TO_SEE_ENGINE = lambda: MergeTreeEngine("sharded_ingestion_warnings")
CREATE_METRICS_TIME_TO_SEE = (
    lambda: f"""
CREATE TABLE metrics_time_to_see_data ON CLUSTER 'posthog' (
    `query_id` String,
    `team_id` UInt64,
    `user_id` UInt64,
    `session_id` String,
    `team_events_last_month` UInt64,
    `timestamp` DateTime64,
    `time_to_see_data_ms` UInt64,
    `api_response_bytes` UInt64,
    `insight_type` LowCardinality(String),
    `cached` UInt8,
    `endpoint` String
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {METRICS_TIME_TO_SEE_ENGINE()}
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), session_id, user_id)
"""
)

DROP_METRICS_TIME_TO_SEE_TABLE = "DROP TABLE metrics_time_to_see_data ON CLUSTER '{CLICKHOUSE_CLUSTER}' SYNC"

CREATE_KAFKA_METRICS_TIME_TO_SEE = (
    lambda: f"""
CREATE TABLE kafka_metrics_time_to_see_data ON CLUSTER '{CLICKHOUSE_CLUSTER}]' (
    `query_id` String,
    `team_id` UInt64,
    `user_id` UInt64,
    `session_id` String,
    `timestamp` DateTime64,
    `time_to_see_data_ms` UInt64,
    `api_response_bytes` UInt64,
    `insight_type` LowCardinality(String),
    `cached` UInt8,
    `endpoint` String
)
ENGINE={kafka_engine(topic=KAFKA_METRICS_TIME_TO_SEE_DATA)}
SETTINGS kafka_skip_broken_messages = 9999
"""
)
DROP_KAFKA_METRICS_TIME_TO_SEE = "DROP TABLE kafka_metrics_time_to_see_data ON CLUSTER '{CLICKHOUSE_CLUSTER}' SYNC"

CREATE_METRICS_TIME_TO_SEE_MV = (
    lambda: f"""
CREATE MATERIALIZED VIEW metrics_time_to_see_data_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'
TO {CLICKHOUSE_DATABASE}.metrics_time_to_see_data
AS SELECT
query_id,
team_id,
user_id,
session_id,
dictGet('team_events_last_month_dictionary', 'event_count', team_id) AS team_events_last_month,
timestamp,
time_to_see_data_ms,
api_response_bytes,
insight_type,
cached,
endpoint,
_timestamp,
_offset,
_partition
FROM {CLICKHOUSE_DATABASE}.kafka_metrics_time_to_see_data
"""
)
DROP_METRICS_TIME_TO_SEE_MV = "DROP TABLE metrics_time_to_see_data_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}' SYNC"

# :KLUDGE: Temporary tooling to make (re)creating this schema easier
if __name__ == "__main__":
    print("To drop query metrics schema:\n")  # noqa: T201
    for drop_query in reversed(
        [
            DROP_TEAM_EVENTS_LAST_MONTH_VIEW,
            DROP_TEAM_EVENTS_LAST_MONTH_DICTIONARY,
            DROP_METRICS_TIME_TO_SEE_TABLE,
            DROP_KAFKA_METRICS_TIME_TO_SEE,
            DROP_METRICS_TIME_TO_SEE_MV,
        ]
    ):
        print(drop_query)  # noqa: T201
        print()  # noqa: T201

    print("To create query metrics schema:\n")  # noqa: T201
    for create_query in [
        CREATE_TEAM_EVENTS_LAST_MONTH_VIEW,
        CREATE_TEAM_EVENTS_LAST_MONTH_DICTIONARY,
        CREATE_METRICS_TIME_TO_SEE,
        CREATE_KAFKA_METRICS_TIME_TO_SEE,
        CREATE_METRICS_TIME_TO_SEE_MV,
    ]:
        print(create_query)  # noqa: T201
        print()  # noqa: T201
