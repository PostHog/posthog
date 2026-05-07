CREATE TABLE IF NOT EXISTS writeable_performance_events ON CLUSTER 'posthog'
(
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
unload_event_start Float64
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

) ENGINE = Distributed('posthog', 'default', 'sharded_performance_events', sipHash64(session_id))

CREATE TABLE IF NOT EXISTS performance_events ON CLUSTER 'posthog'
(
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
unload_event_start Float64
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

) ENGINE = Distributed('posthog', 'default', 'sharded_performance_events', sipHash64(session_id))

CREATE TABLE IF NOT EXISTS sharded_performance_events ON CLUSTER 'posthog'
(
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
unload_event_start Float64
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

) ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/posthog.performance_events', '{replica}')
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), session_id, pageview_id, timestamp)
TTL toDate(timestamp) + INTERVAL 3 WEEK

CREATE TABLE IF NOT EXISTS kafka_performance_events ON CLUSTER 'posthog'
(
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
unload_event_start Float64
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_performance_events', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS performance_events_mv ON CLUSTER 'posthog'
TO default.writeable_performance_events
AS SELECT
uuid, session_id, window_id, pageview_id, distinct_id, timestamp, time_origin, entry_type, name, team_id, current_url, start_time, duration, redirect_start, redirect_end, worker_start, fetch_start, domain_lookup_start, domain_lookup_end, connect_start, secure_connection_start, connect_end, request_start, response_start, response_end, decoded_body_size, encoded_body_size, initiator_type, next_hop_protocol, render_blocking_status, response_status, transfer_size, largest_contentful_paint_element, largest_contentful_paint_render_time, largest_contentful_paint_load_time, largest_contentful_paint_size, largest_contentful_paint_id, largest_contentful_paint_url, dom_complete, dom_content_loaded_event, dom_interactive, load_event_end, load_event_start, redirect_count, navigation_type, unload_event_end, unload_event_start
,_timestamp, _offset, _partition
FROM default.kafka_performance_events
