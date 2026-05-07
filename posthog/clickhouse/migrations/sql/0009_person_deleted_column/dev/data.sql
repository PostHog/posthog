DROP TABLE IF EXISTS person_mv ON CLUSTER 'posthog'

DROP TABLE IF EXISTS kafka_person ON CLUSTER 'posthog'

ALTER TABLE person ADD COLUMN IF NOT EXISTS is_deleted Int8 DEFAULT 0

CREATE TABLE IF NOT EXISTS kafka_person ON CLUSTER 'posthog'
(
    id UUID,
    created_at DateTime64,
    team_id Int64,
    properties VARCHAR,
    is_identified Int8,
    is_deleted Int8,
    version UInt64,
    last_seen_at Nullable(DateTime64)
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_person', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS person_mv ON CLUSTER 'posthog'
TO person
AS SELECT
id,
created_at,
team_id,
properties,
is_identified,
is_deleted,
version,
last_seen_at,
_timestamp,
_offset
FROM kafka_person
