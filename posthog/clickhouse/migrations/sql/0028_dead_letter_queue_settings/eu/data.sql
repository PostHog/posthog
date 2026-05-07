DROP TABLE IF EXISTS events_dead_letter_queue_mv ON CLUSTER 'posthog'

DROP TABLE IF EXISTS kafka_events_dead_letter_queue ON CLUSTER 'posthog'

CREATE TABLE IF NOT EXISTS kafka_events_dead_letter_queue ON CLUSTER 'posthog'
(
    id UUID,
    event_uuid UUID,
    event VARCHAR,
    properties VARCHAR,
    distinct_id VARCHAR,
    team_id Int64,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC'),
    ip VARCHAR,
    site_url VARCHAR,
    now DateTime64(6, 'UTC'),
    raw_payload VARCHAR,
    error_timestamp DateTime64(6, 'UTC'),
    error_location VARCHAR,
    error VARCHAR,
    tags Array(VARCHAR)
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'events_dead_letter_queue', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')
 SETTINGS kafka_skip_broken_messages=1000

CREATE MATERIALIZED VIEW IF NOT EXISTS events_dead_letter_queue_mv ON CLUSTER 'posthog'
TO default.events_dead_letter_queue
AS SELECT
id,
event_uuid,
event,
properties,
distinct_id,
team_id,
elements_chain,
created_at,
ip,
site_url,
now,
raw_payload,
error_timestamp,
error_location,
error,
tags,
_timestamp,
_offset
FROM default.kafka_events_dead_letter_queue
