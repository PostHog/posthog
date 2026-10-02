from posthog import settings
from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.kafka_client.topics import KAFKA_PERFORMANCE_EVENTS

"""https://developer.mozilla.org/en-US/docs/Web/API/PerformanceEntry"""


"""
# expected queries

## get all performance events for a given team's session

allows us to show performance events alongside other logs while viewing a session recording

shard by session id so that when querying for all in session or pageview all data for the results are on the same shard

SELECT * FROM performance_events
WHERE team_id = 1
AND session_id = 'my-session-uuid'
AND timestamp >= {before-the-session}
AND timestamp < now()
ORDER BY timestamp

## get all performance events for a given team's pageview

allows us to show performance events in a waterfall chart for a given pageview

SELECT * FROM performance_events
WHERE team_id = 1
AND session_id = 'my-session-uuid'
AND pageview_id = 'my-page-view-uuid' -- sent by SDK
AND timestamp >= {before-the-session}
AND timestamp < now()
ORDER BY timestamp

## all other queries are expected to be based on aggregating materialized views built from this fact table
"""


def PERFORMANCE_EVENT_DATA_TABLE():
    return "sharded_performance_events"


def UPDATE_PERFORMANCE_EVENTS_TABLE_TTL_SQL():
    return f"ALTER TABLE {PERFORMANCE_EVENT_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' MODIFY TTL toDate(timestamp) + toIntervalWeek(%(weeks)s)"


PERFORMANCE_EVENT_COLUMNS = """
uuid UUID,
session_id String,
window_id String,
pageview_id String,
distinct_id String,
timestamp DateTime64,
time_origin DateTime64(3, 'UTC'),
entry_type LowCardinality(String),
name String,
team_id Int64,
current_url String,
start_time Float64,
duration Float64,
redirect_start Float64,
redirect_end Float64,
worker_start Float64,
fetch_start Float64,
domain_lookup_start Float64,
domain_lookup_end Float64,
connect_start Float64,
secure_connection_start Float64,
connect_end Float64,
request_start Float64,
response_start Float64,
response_end Float64,
decoded_body_size Int64,
encoded_body_size Int64,
initiator_type LowCardinality(String),
next_hop_protocol LowCardinality(String),
render_blocking_status LowCardinality(String),
response_status Int64,
transfer_size Int64,
largest_contentful_paint_element String,
largest_contentful_paint_render_time Float64,
largest_contentful_paint_load_time Float64,
largest_contentful_paint_size Float64,
largest_contentful_paint_id String,
largest_contentful_paint_url String,
dom_complete Float64,
dom_content_loaded_event Float64,
dom_interactive Float64,
load_event_end Float64,
load_event_start Float64,
redirect_count Int64,
navigation_type LowCardinality(String),
unload_event_end Float64,
unload_event_start Float64,
""".strip().rstrip(",")

PERFORMANCE_EVENTS_TABLE_BASE_SQL = lambda: (
    """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    {columns}
    {extra_fields}
) ENGINE = {engine}
"""
)


def KAFKA_PERFORMANCE_EVENTS_TABLE_SQL(on_cluster=True):
    return PERFORMANCE_EVENTS_TABLE_BASE_SQL().format(
        columns=PERFORMANCE_EVENT_COLUMNS,
        table_name="kafka_performance_events",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(topic=KAFKA_PERFORMANCE_EVENTS),
        extra_fields="",
    )
