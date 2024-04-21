from datetime import datetime

from django.utils.timezone import now

from posthog import settings
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.kafka_engine import (
    KAFKA_COLUMNS_WITH_PARTITION,
    STORAGE_POLICY,
    kafka_engine,
    ttl_period,
)
from posthog.clickhouse.table_engines import (
    Distributed,
    MergeTreeEngine,
    ReplicationScheme,
)
from posthog.kafka_client.topics import KAFKA_PERFORMANCE_EVENTS

"""
see https://developer.mozilla.org/en-US/docs/Web/API/PerformanceEntry

all of our ingestion is based on this standard because the browser gives it us for free

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
AND pageview_id = 'my-page-view-uuid' -- no longer sent by SDK 😱
AND timestamp >= {before-the-session}
AND timestamp < now()
ORDER BY timestamp

## all other queries are expected to be based on aggregating materialized views built from this fact table

# materialized columns

we gather a bunch of raw data, and can materialize common calculation results when the apprporiate values are present

kafka, the MV, and the writeable table do not have the materialized columns listed
the sharded (local) tables have the materialized columns and their definition
the distributed table has the columns but not their definition

for individual recording playback we calculate these values from the blob stored network data
for analysis we want to be able to offer and aggregate the values so may as well materialize them

# what might we materialize

see https://github.com/PostHog/posthog/blob/6cd02e980ae7d7a93f3da74cbfc8ec634aa86339/frontend/src/scenes/session-recordings/player/inspector/components/Timing/NetworkRequestTiming.tsx#L128

## we can assert that something was from a cache

we probably don't need to materialize this

`const isFromLocalCache = item.transfer_size === 0 && (item.decoded_body_size || 0) > 0`

## dom processing

if both are present `perfEntry.load_event_end - perfEntry.response_end > 0` are the DOM processsing time

## TTFB

time to first byte is a useful measure
it is the time between the start of the performance entry and the response_start

in replay display if both are present we use
`perfEntry.response_start - perfEntry.request_start > 0`

## network timing

if both are present perfEntry.start_time to perfEntry.response_end

"""

PERFORMANCE_EVENT_COLUMNS = """
timestamp DateTime64,
distinct_id String,
session_id String,
window_id String,
team_id Int64,
current_url String,
time_origin Nullable(DateTime64(3, 'UTC')),
entry_type LowCardinality(String),
name String,
start_time Nullable(Float64),
duration Nullable(Float64),
redirect_start Nullable(Float64),
redirect_end Nullable(Float64),
worker_start Nullable(Float64),
fetch_start Nullable(Float64),
domain_lookup_start Nullable(Float64),
domain_lookup_end Nullable(Float64),
connect_start Nullable(Float64),
secure_connection_start Nullable(Float64),
connect_end Nullable(Float64),
request_start Nullable(Float64),
response_start Nullable(Float64),
response_end Nullable(Float64),
decoded_body_size Nullable(Int64),
encoded_body_size Nullable(Int64),
initiator_type LowCardinality(String),
next_hop_protocol LowCardinality(String),
render_blocking_status LowCardinality(String),
response_status Nullable(Int64),
transfer_size Nullable(Int64),
largest_contentful_paint_element String,
largest_contentful_paint_render_time Nullable(Float64),
largest_contentful_paint_load_time Nullable(Float64),
largest_contentful_paint_size Nullable(Float64),
largest_contentful_paint_id String,
largest_contentful_paint_url String,
dom_complete Nullable(Float64),
dom_content_loaded_event Nullable(Float64),
dom_interactive Nullable(Float64),
load_event_end Nullable(Float64),
load_event_start Nullable(Float64),
redirect_count Nullable(Int64),
navigation_type LowCardinality(String),
unload_event_end Nullable(Float64),
unload_event_start Nullable(Float64),
method LowCardinality(String),
is_initial boolean
""".strip().rstrip(",")


def zk_unique_table_engine():
    engine = MergeTreeEngine("performance_events", replication_scheme=ReplicationScheme.SHARDED)
    # :TRICKY: Zookeeper paths need to be unique - it isn't cleaned up when we drop tables
    # in migration 0060 we're dropping and recreating the table
    engine.set_zookeeper_path_key(now().strftime("CHM0060_%Y%m%d%H%M%S"))
    return engine


PERFORMANCE_EVENT_TABLE_ENGINE = lambda: MergeTreeEngine(
    "performance_events", replication_scheme=ReplicationScheme.SHARDED
)

PERFORMANCE_EVENT_DATA_TABLE = lambda: "sharded_performance_events"

PERFORMANCE_EVENTS_TABLE_BASE_SQL = (
    lambda: """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    {columns}
    {extra_fields}
) ENGINE = {engine}
"""
)

PERFORMANCE_EVENTS_TABLE_SQL = lambda: (
    PERFORMANCE_EVENTS_TABLE_BASE_SQL()
    + """PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), session_id, timestamp)
{ttl_period}
{storage_policy}
"""
).format(
    columns=PERFORMANCE_EVENT_COLUMNS,
    table_name=PERFORMANCE_EVENT_DATA_TABLE(),
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=zk_unique_table_engine(),
    extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
    ttl_period=ttl_period(field="timestamp"),
    storage_policy=STORAGE_POLICY(),
)

KAFKA_PERFORMANCE_EVENTS_TABLE_SQL = lambda: PERFORMANCE_EVENTS_TABLE_BASE_SQL().format(
    columns=PERFORMANCE_EVENT_COLUMNS,
    table_name="kafka_performance_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
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


DISTRIBUTED_PERFORMANCE_EVENTS_TABLE_SQL = lambda: PERFORMANCE_EVENTS_TABLE_BASE_SQL().format(
    columns=PERFORMANCE_EVENT_COLUMNS,
    table_name="performance_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(
        data_table=PERFORMANCE_EVENT_DATA_TABLE(),
        sharding_key="sipHash64(session_id)",
    ),
    extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
)

WRITABLE_PERFORMANCE_EVENTS_TABLE_SQL = lambda: PERFORMANCE_EVENTS_TABLE_BASE_SQL().format(
    columns=PERFORMANCE_EVENT_COLUMNS,
    table_name="writeable_performance_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
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
select session_id, name, duration, timestamp
from performance_events
prewhere team_id = %(team_id)s
and timestamp >= %(date_from)s
and timestamp <= %(date_to)s
and entry_type = 'navigation'
order by timestamp desc
"""

TRUNCATE_PERFORMANCE_EVENTS_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {PERFORMANCE_EVENT_DATA_TABLE()}"

UPDATE_PERFORMANCE_EVENTS_TABLE_TTL_SQL = lambda: (
    f"ALTER TABLE {PERFORMANCE_EVENT_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' MODIFY TTL toDate(timestamp) + toIntervalWeek(%(weeks)s)"
)


def insert_single_network_performance_event(
    team_id: int,
    timestamp: datetime | None = None,
    distinct_id: str | None = None,
    session_id: str | None = None,
    window_id: str | None = None,
    current_url: str | None = None,
    time_origin: datetime | None = None,
    entry_type: str | None = None,
    name: str | None = None,
    start_time: float | None = None,
    duration: float | None = None,
    redirect_start: float | None = None,
    redirect_end: float | None = None,
    worker_start: float | None = None,
    fetch_start: float | None = None,
    domain_lookup_start: float | None = None,
    domain_lookup_end: float | None = None,
    connect_start: float | None = None,
    secure_connection_start: float | None = None,
    connect_end: float | None = None,
    request_start: float | None = None,
    response_start: float | None = None,
    response_end: float | None = None,
    decoded_body_size: int | None = None,
    encoded_body_size: int | None = None,
    initiator_type: str | None = None,
    next_hop_protocol: str | None = None,
    render_blocking_status: str | None = None,
    response_status: int | None = None,
    transfer_size: int | None = None,
    largest_contentful_paint_element: str | None = None,
    largest_contentful_paint_render_time: float | None = None,
    largest_contentful_paint_load_time: float | None = None,
    largest_contentful_paint_size: float | None = None,
    largest_contentful_paint_id: str | None = None,
    largest_contentful_paint_url: str | None = None,
    dom_complete: float | None = None,
    dom_content_loaded_event: float | None = None,
    dom_interactive: float | None = None,
    load_event_end: float | None = None,
    load_event_start: float | None = None,
    redirect_count: int | None = None,
    navigation_type: str | None = None,
    unload_event_end: float | None = None,
    unload_event_start: float | None = None,
    method: str | None = None,
    is_initial: bool = False,
) -> None:
    if timestamp is None:
        timestamp = datetime.now()

    sync_execute(
        """
INSERT INTO sharded_performance_events (
timestamp,
distinct_id,
session_id,
window_id,
team_id,
current_url,
time_origin,
entry_type,
name,
start_time,
duration,
redirect_start,
redirect_end,
worker_start,
fetch_start,
domain_lookup_start,
domain_lookup_end,
connect_start,
secure_connection_start,
connect_end,
request_start,
response_start,
response_end,
decoded_body_size,
encoded_body_size,
initiator_type,
next_hop_protocol,
render_blocking_status,
response_status,
transfer_size,
largest_contentful_paint_element,
largest_contentful_paint_render_time,
largest_contentful_paint_load_time,
largest_contentful_paint_size,
largest_contentful_paint_id,
largest_contentful_paint_url,
dom_complete,
dom_content_loaded_event,
dom_interactive,
load_event_end,
load_event_start,
redirect_count,
navigation_type,
unload_event_end,
unload_event_start,
method,
is_initial
)
SELECT
%(timestamp)s,
%(distinct_id)s,
%(session_id)s,
%(window_id)s,
%(team_id)s,
%(current_url)s,
%(time_origin)s,
%(entry_type)s,
%(name)s,
%(start_time)s,
%(duration)s,
%(redirect_start)s,
%(redirect_end)s,
%(worker_start)s,
%(fetch_start)s,
%(domain_lookup_start)s,
%(domain_lookup_end)s,
%(connect_start)s,
%(secure_connection_start)s,
%(connect_end)s,
%(request_start)s,
%(response_start)s,
%(response_end)s,
%(decoded_body_size)s,
%(encoded_body_size)s,
%(initiator_type)s,
%(next_hop_protocol)s,
%(render_blocking_status)s,
%(response_status)s,
%(transfer_size)s,
%(largest_contentful_paint_element)s,
%(largest_contentful_paint_render_time)s,
%(largest_contentful_paint_load_time)s,
%(largest_contentful_paint_size)s,
%(largest_contentful_paint_id)s,
%(largest_contentful_paint_url)s,
%(dom_complete)s,
%(dom_content_loaded_event)s,
%(dom_interactive)s,
%(load_event_end)s,
%(load_event_start)s,
%(redirect_count)s,
%(navigation_type)s,
%(unload_event_end)s,
%(unload_event_start)s,
%(method)s,
%(is_initial)s
""",
        {
            "timestamp": timestamp,
            "distinct_id": distinct_id,
            "session_id": session_id,
            "window_id": window_id,
            "team_id": team_id,
            "current_url": current_url,
            "time_origin": time_origin,
            "entry_type": entry_type,
            "name": name,
            "start_time": start_time,
            "duration": duration,
            "redirect_start": redirect_start,
            "redirect_end": redirect_end,
            "worker_start": worker_start,
            "fetch_start": fetch_start,
            "domain_lookup_start": domain_lookup_start,
            "domain_lookup_end": domain_lookup_end,
            "connect_start": connect_start,
            "secure_connection_start": secure_connection_start,
            "connect_end": connect_end,
            "request_start": request_start,
            "response_start": response_start,
            "response_end": response_end,
            "decoded_body_size": decoded_body_size,
            "encoded_body_size": encoded_body_size,
            "initiator_type": initiator_type,
            "next_hop_protocol": next_hop_protocol,
            "render_blocking_status": render_blocking_status,
            "response_status": response_status,
            "transfer_size": transfer_size,
            "largest_contentful_paint_element": largest_contentful_paint_element,
            "largest_contentful_paint_render_time": largest_contentful_paint_render_time,
            "largest_contentful_paint_load_time": largest_contentful_paint_load_time,
            "largest_contentful_paint_size": largest_contentful_paint_size,
            "largest_contentful_paint_id": largest_contentful_paint_id,
            "largest_contentful_paint_url": largest_contentful_paint_url,
            "dom_complete": dom_complete,
            "dom_content_loaded_event": dom_content_loaded_event,
            "dom_interactive": dom_interactive,
            "load_event_end": load_event_end,
            "load_event_start": load_event_start,
            "redirect_count": redirect_count,
            "navigation_type": navigation_type,
            "unload_event_end": unload_event_end,
            "unload_event_start": unload_event_start,
            "method": method,
            "is_initial": is_initial,
        },
    )
