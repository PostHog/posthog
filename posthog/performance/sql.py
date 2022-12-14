"""https://developer.mozilla.org/en-US/docs/Web/API/PerformanceEntry"""
from posthog import settings
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION, STORAGE_POLICY, kafka_engine
from posthog.clickhouse.table_engines import Distributed, MergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_PERFORMANCE_EVENTS

# TODO
# explode server timing from Resource events into their own columns

"""
# expected queries

## get all performance events for a given team's session

allows us to show performance events alongside other logs while viewing a session recording

shard by session id so that when querying for all in session or pageview all data for the results are on the same shard

SELECT * FROM performance_events
WHERE team_id = 1
AND session_id = 'my-session-uuid'
ORDER BY timestamp DESC

## get all performance events for a given team's pageview

allows us to show performance events in a waterfall chart for a given pageview

SELECT * FROM performance_events
WHERE team_id = 1
AND pageview_id = 'my-page-view-uuid' -- sent by SDK
ORDER BY timestamp DESC

## all other queries are expected to be based on aggregating materialized views built from this fact table
"""

PERFORMANCE_EVENT_COLUMNS = """
uuid UUID,
session_id String,
window_id String,
pageview_id String,
distinct_id String,
time_origin DateTime64(3, 'UTC'),
entry_type LowCardinality(String),
name String,
team_id Int64,
current_url String,
start_time Float64,
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
""".strip().rstrip(
    ","
)

PERFORMANCE_EVENT_TABLE_ENGINE = lambda: MergeTree("performance_events", replication_scheme=ReplicationScheme.SHARDED)

PERFORMANCE_EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    {columns}
    {extra_fields}
) ENGINE = {engine}
"""

"""
I think this says store the data on disk grouped by team_id,
within that group it by session id,
within that group it by pageview id,

thus in order to query it we are supporting

`where team_id=X`

OR

`where team_id=X and session_id=Y`

OR

`where team_id=X and session_id=Y and pageview_id=Z`
"""
PERFORMANCE_EVENTS_TABLE_SQL = (
    PERFORMANCE_EVENTS_TABLE_BASE_SQL
    + """PARTITION BY toYYYYMM(time_origin)
ORDER BY (team_id, session_id, pageview_id)
{storage_policy}
"""
).format(
    columns=PERFORMANCE_EVENT_COLUMNS,
    table_name="sharded_performance_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=PERFORMANCE_EVENT_TABLE_ENGINE(),
    extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
    storage_policy=STORAGE_POLICY(),
)

KAFKA_PERFORMANCE_EVENTS_TABLE_SQL = PERFORMANCE_EVENTS_TABLE_BASE_SQL.format(
    columns=PERFORMANCE_EVENT_COLUMNS,
    table_name="kafka_performance_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=kafka_engine(topic=KAFKA_PERFORMANCE_EVENTS),
    extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
)


def _column_names_from_column_definitions(column_definitions: str) -> str:
    """
    this avoids manually duplicating column names from a string defining the columns earlier in the file
    when creating the materialized view
    """

    def clean_line(line: str) -> str:
        return line.strip().strip(",").strip()

    return ",".join([clean_line(line).split(" ")[0] for line in column_definitions.split("\n") if clean_line(line)])


PERFORMANCE_EVENTS_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW performance_events_mv ON CLUSTER '{cluster}'
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

WRITABLE_PERFORMANCE_EVENTS_TABLE_SQL = PERFORMANCE_EVENTS_TABLE_BASE_SQL.format(
    columns=PERFORMANCE_EVENT_COLUMNS,
    table_name="writeable_performance_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(data_table="sharded_performance_events", sharding_key="sipHash64(session_id)"),
    extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
)

DISTRIBUTED_PERFORMANCE_EVENTS_TABLE_SQL = PERFORMANCE_EVENTS_TABLE_BASE_SQL.format(
    columns=PERFORMANCE_EVENT_COLUMNS,
    table_name="performance_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(data_table="sharded_performance_events", sharding_key="sipHash64(session_id)"),
    extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
)
