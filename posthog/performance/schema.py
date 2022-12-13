"""https://developer.mozilla.org/en-US/docs/Web/API/PerformanceEntry"""
from posthog import settings
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION, STORAGE_POLICY, kafka_engine
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_PERFORMANCE_EVENTS

# TODO
# explode server timing from Resource events into their own columns
# /* time origin is in milliseconds e.g. 1670900799301.7 */

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

BASE_PERFORMANCE_EVENT_COLUMNS = """
uuid UUID,
session_id UUID,
window_id UUID,
pageview_id UUID,
time_origin Int64,
origin_timestamp DateTime64(3, 'UTC'),
entry_type LowCardinality(String),
name String,
team_id Int64,
current_url String,
""".strip()

"""https://developer.mozilla.org/en-US/docs/Web/API/PerformanceResourceTiming"""
RESOURCE_EVENT_COLUMNS = """
start_time Int64,
redirect_start Int64,
redirect_end Int64,
worker_start Int64,
fetch_start Int64,
domain_lookup_start Int64,
domain_lookup_end Int64,
connect_start Int64,
secure_connection_start Int64,
connect_end Int64,
request_start Int64,
response_start Int64,
response_end Int64,
decoded_body_size Int64,
encoded_body_size Int64,
initiator_type LowCardinality(String),
next_hop_protocol LowCardinality(String),
render_blocking_status LowCardinality(String),
response_status Int64,
transfer_size Int64,
""".strip()

"""https://developer.mozilla.org/en-US/docs/Web/API/LargestContentfulPaint"""
LARGEST_CONTENTFUL_PAINT_EVENT_COLUMNS = """
largest_contentful_paint_element String,
largest_contentful_paint_render_time Int64,
largest_contentful_paint_load_time Int64,
largest_contentful_paint_size Int64,
largest_contentful_paint_id String,
largest_contentful_paint_url String,
""".strip()

"""https://developer.mozilla.org/en-US/docs/Web/API/PerformanceNavigationTiming"""
NAVIGATION_EVENT_COLUMNS = """
dom_complete Int64,
dom_content_loaded_event Int64,
dom_interactive Int64,
load_event_end Int64,
load_event_start Int64,
redirect_count Int64,
navigation_type LowCardinality(String),
unload_event_end Int64,
unload_event_start Int64,
""".strip()

columns = ",".join(
    [
        BASE_PERFORMANCE_EVENT_COLUMNS.rstrip(","),
        RESOURCE_EVENT_COLUMNS.rstrip(","),
        LARGEST_CONTENTFUL_PAINT_EVENT_COLUMNS.rstrip(","),
        NAVIGATION_EVENT_COLUMNS.rstrip(","),
    ]
)

PERFORMANCE_EVENT_TABLE_ENGINE = lambda: ReplacingMergeTree(
    "performance_events", ver="_timestamp", replication_scheme=ReplicationScheme.SHARDED
)

PERFORMANCE_EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    {columns}
    {extra_fields}
) ENGINE = {engine}
"""

PERFORMANCE_EVENTS_TABLE_SQL = (
    PERFORMANCE_EVENTS_TABLE_BASE_SQL
    + """PARTITION BY toYYYYMM(origin_timestamp)
ORDER BY (team_id, toDate(origin_timestamp), session_id, pageview_id)
{storage_policy}
"""
).format(
    columns=columns,
    table_name="sharded_performance_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=PERFORMANCE_EVENT_TABLE_ENGINE(),
    extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
    storage_policy=STORAGE_POLICY(),
)

KAFKA_PERFORMANCE_EVENTS_TABLE_SQL = PERFORMANCE_EVENTS_TABLE_BASE_SQL.format(
    columns=columns,
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
{extra_fields}
FROM {database}.kafka_performance_events
""".format(
    columns=_column_names_from_column_definitions(columns),
    target_table="writeable_performance_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    database=settings.CLICKHOUSE_DATABASE,
    extra_fields=_column_names_from_column_definitions(KAFKA_COLUMNS_WITH_PARTITION),
)

# This table is responsible for writing to sharded_events based on a sharding key.
WRITABLE_PERFORMANCE_EVENTS_TABLE_SQL = PERFORMANCE_EVENTS_TABLE_BASE_SQL.format(
    columns=columns,
    table_name="writeable_performance_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(data_table="sharded_performance_events", sharding_key="sipHash64(session_id)"),
    extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
)

# This table is responsible for reading from events on a cluster setting
DISTRIBUTED_PERFORMANCE_EVENTS_TABLE_SQL = PERFORMANCE_EVENTS_TABLE_BASE_SQL.format(
    columns=columns,
    table_name="performance_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(data_table="sharded_performance_events", sharding_key="sipHash64(session_id)"),
    extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
)
