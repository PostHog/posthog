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

DROP_TEAM_EVENTS_LAST_MONTH_VIEW = lambda: f"DROP TABLE team_events_last_month_view ON CLUSTER '{CLICKHOUSE_CLUSTER}'"

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

DROP_TEAM_EVENTS_LAST_MONTH_DICTIONARY = lambda: (
    f"DROP DICTIONARY team_events_last_month_dictionary ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
)

METRICS_TIME_TO_SEE_ENGINE = lambda: MergeTreeEngine("sharded_ingestion_warnings", force_unique_zk_path=True)
CREATE_METRICS_TIME_TO_SEE = (
    lambda: f"""
CREATE TABLE metrics_time_to_see_data ON CLUSTER 'posthog' (
    `team_events_last_month` UInt64,
    `query_id` String,
    `team_id` UInt64,
    `user_id` UInt64,
    `session_id` String,
    `timestamp` DateTime64,
    `type` LowCardinality(String),
    `context` LowCardinality(String),
    `time_to_see_data_ms` UInt64,
    `status` LowCardinality(String),
    `api_response_bytes` UInt64,
    `current_url` String,
    `api_url` String,
    `insight` LowCardinality(String),
    `action` LowCardinality(String),
    `insights_fetched` UInt16,
    `insights_fetched_cached` UInt16,
    `min_last_refresh` DateTime64,
    `max_last_refresh` DateTime64
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {METRICS_TIME_TO_SEE_ENGINE()}
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), session_id, user_id)
"""
)

DROP_METRICS_TIME_TO_SEE_TABLE = lambda: f"DROP TABLE metrics_time_to_see_data ON CLUSTER '{CLICKHOUSE_CLUSTER}' SYNC"

CREATE_KAFKA_METRICS_TIME_TO_SEE = (
    lambda: f"""
CREATE TABLE kafka_metrics_time_to_see_data ON CLUSTER '{CLICKHOUSE_CLUSTER}' (
    `team_events_last_month` UInt64,
    `query_id` String,
    `team_id` UInt64,
    `user_id` UInt64,
    `session_id` String,
    `timestamp` DateTime64,
    `type` LowCardinality(String),
    `context` LowCardinality(String),
    `time_to_see_data_ms` UInt64,
    `status` LowCardinality(String),
    `api_response_bytes` UInt64,
    `current_url` String,
    `api_url` String,
    `insight` LowCardinality(String),
    `action` LowCardinality(String),
    `insights_fetched` UInt16,
    `insights_fetched_cached` UInt16,
    `min_last_refresh` DateTime64,
    `max_last_refresh` DateTime64
)
ENGINE={kafka_engine(topic=KAFKA_METRICS_TIME_TO_SEE_DATA)}
SETTINGS kafka_skip_broken_messages = 9999
"""
)
DROP_KAFKA_METRICS_TIME_TO_SEE = (
    lambda: f"DROP TABLE kafka_metrics_time_to_see_data ON CLUSTER '{CLICKHOUSE_CLUSTER}' SYNC"
)

CREATE_METRICS_TIME_TO_SEE_MV = (
    lambda: f"""
CREATE MATERIALIZED VIEW metrics_time_to_see_data_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'
TO {CLICKHOUSE_DATABASE}.metrics_time_to_see_data
AS SELECT
dictGet('team_events_last_month_dictionary', 'event_count', team_id) AS team_events_last_month,
query_id,
team_id,
user_id,
session_id,
timestamp,
type,
context,
time_to_see_data_ms,
status,
api_response_bytes,
current_url,
api_url,
insight,
action,
insights_fetched,
insights_fetched_cached,
min_last_refresh,
max_last_refresh,
_timestamp,
_offset,
_partition
FROM {CLICKHOUSE_DATABASE}.kafka_metrics_time_to_see_data
"""
)
DROP_METRICS_TIME_TO_SEE_MV = lambda: f"DROP TABLE metrics_time_to_see_data_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}' SYNC"

# :KLUDGE: Temporary tooling to make (re)creating this schema easier
# Invoke via `python manage.py shell <  posthog/models/query_metrics/sql.py`
if __name__ == "django.core.management.commands.shell":
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
        print(drop_query())  # noqa: T201
        print()  # noqa: T201

    print("To create query metrics schema:\n")  # noqa: T201
    for create_query in [
        CREATE_TEAM_EVENTS_LAST_MONTH_VIEW,
        CREATE_TEAM_EVENTS_LAST_MONTH_DICTIONARY,
        CREATE_METRICS_TIME_TO_SEE,
        CREATE_KAFKA_METRICS_TIME_TO_SEE,
        CREATE_METRICS_TIME_TO_SEE_MV,
    ]:
        print(create_query())  # noqa: T201
        print()  # noqa: T201
