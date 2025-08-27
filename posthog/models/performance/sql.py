"""https://developer.mozilla.org/en-US/docs/Web/API/PerformanceEntry"""

from posthog import settings
from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION, STORAGE_POLICY, kafka_engine, ttl_period
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_PERFORMANCE_EVENTS

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


def PERFORMANCE_EVENT_TABLE_ENGINE():
    return MergeTreeEngine("performance_events", replication_scheme=ReplicationScheme.SHARDED)


def PERFORMANCE_EVENT_DATA_TABLE():
    return "sharded_performance_events"


PERFORMANCE_EVENTS_TABLE_BASE_SQL = (
    lambda: """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    {columns}
    {extra_fields}
) ENGINE = {engine}
"""
)


def PERFORMANCE_EVENTS_TABLE_SQL(on_cluster=True):
    return (
        PERFORMANCE_EVENTS_TABLE_BASE_SQL()
        + """PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), session_id, pageview_id, timestamp)
{ttl_period}
{storage_policy}
"""
    ).format(
        columns=PERFORMANCE_EVENT_COLUMNS,
        table_name=PERFORMANCE_EVENT_DATA_TABLE(),
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=PERFORMANCE_EVENT_TABLE_ENGINE(),
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
        ttl_period=ttl_period(field="timestamp"),
        storage_policy=STORAGE_POLICY(),
    )


def KAFKA_PERFORMANCE_EVENTS_TABLE_SQL(on_cluster=True):
    return PERFORMANCE_EVENTS_TABLE_BASE_SQL().format(
        columns=PERFORMANCE_EVENT_COLUMNS,
        table_name="kafka_performance_events",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(topic=KAFKA_PERFORMANCE_EVENTS),
        extra_fields="",
    )


def _clean_line(line: str) -> str:
    return line.strip().strip(",").strip()


def _column_names_from_column_definitions(column_definitions: str) -> str:
    """
    this avoids manually duplicating column names from a string defining the columns earlier in the file
    when creating the materialized view
    """
    column_names = []
    for line in column_definitions.splitlines():
        column_name = _clean_line(line).split(" ")[0]
        column_names.append(column_name)

    return ", ".join([cl for cl in column_names if cl])


def DISTRIBUTED_PERFORMANCE_EVENTS_TABLE_SQL(on_cluster=True):
    return PERFORMANCE_EVENTS_TABLE_BASE_SQL().format(
        columns=PERFORMANCE_EVENT_COLUMNS,
        table_name="performance_events",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(
            data_table=PERFORMANCE_EVENT_DATA_TABLE(),
            sharding_key="sipHash64(session_id)",
        ),
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
    )


def WRITABLE_PERFORMANCE_EVENTS_TABLE_SQL(on_cluster=True):
    return PERFORMANCE_EVENTS_TABLE_BASE_SQL().format(
        columns=PERFORMANCE_EVENT_COLUMNS,
        table_name="writeable_performance_events",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(
            data_table=PERFORMANCE_EVENT_DATA_TABLE(),
            sharding_key="sipHash64(session_id)",
        ),
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
    )


PERFORMANCE_EVENTS_TABLE_MV_SQL = (
    lambda: """
CREATE MATERIALIZED VIEW IF NOT EXISTS performance_events_mv ON CLUSTER '{cluster}'
TO {database}.{target_table}
AS SELECT
{columns}
,{extra_fields}
FROM {database}.kafka_performance_events
""".format(
        columns=_column_names_from_column_definitions(PERFORMANCE_EVENT_COLUMNS),
        target_table="writeable_performance_events",
        cluster=settings.CLICKHOUSE_CLUSTER,
        database=settings.CLICKHOUSE_DATABASE,
        extra_fields=_column_names_from_column_definitions(KAFKA_COLUMNS_WITH_PARTITION),
    )
)

# TODO this should probably be a materialized view
# because then it could include a count of other events per `pageview_id`
# and because the inclusion of entry_type in the filters here
# might be bad for perf of the query
RECENT_PAGE_VIEWS_SQL = """
select session_id, pageview_id, name, duration, timestamp
from performance_events
prewhere team_id = %(team_id)s
and timestamp >= %(date_from)s
and timestamp <= %(date_to)s
and entry_type = 'navigation'
order by timestamp desc
"""

TRUNCATE_PERFORMANCE_EVENTS_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {PERFORMANCE_EVENT_DATA_TABLE()}"


def UPDATE_PERFORMANCE_EVENTS_TABLE_TTL_SQL():
    return f"ALTER TABLE {PERFORMANCE_EVENT_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' MODIFY TTL toDate(timestamp) + toIntervalWeek(%(weeks)s)"
