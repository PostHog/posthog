CREATE TABLE IF NOT EXISTS kafka_groups_ws 
(
    group_type_index UInt8,
    group_key VARCHAR,
    created_at DateTime64,
    team_id Int64,
    group_properties VARCHAR
    
) ENGINE = Kafka(warpstream_ingestion, kafka_topic_list = 'clickhouse_groups', kafka_group_name = 'clickhouse_groups_ws', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS groups_ws_mv 
TO writable_groups
AS SELECT
group_type_index,
group_key,
created_at,
team_id,
group_properties,
_timestamp,
_offset
FROM kafka_groups_ws

CREATE TABLE IF NOT EXISTS kafka_person_ws 
(
    id UUID,
    created_at DateTime64,
    team_id Int64,
    properties VARCHAR,
    is_identified Int8,
    is_deleted Int8,
    version UInt64,
    last_seen_at Nullable(DateTime64)
    
) ENGINE = Kafka(warpstream_ingestion, kafka_topic_list = 'clickhouse_person', kafka_group_name = 'clickhouse_person_ws', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS person_ws_mv 
TO writable_person
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
FROM kafka_person_ws

CREATE TABLE IF NOT EXISTS kafka_person_distinct_id2_ws 
(
    team_id Int64,
    distinct_id VARCHAR,
    person_id UUID,
    is_deleted Int8,
    version Int64
    
) ENGINE = Kafka(warpstream_ingestion, kafka_topic_list = 'clickhouse_person_distinct_id', kafka_group_name = 'clickhouse_person_distinct_id2_ws', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS person_distinct_id2_ws_mv 
TO writable_person_distinct_id2
AS SELECT
team_id,
distinct_id,
person_id,
is_deleted,
version,
_timestamp,
_offset,
_partition
FROM kafka_person_distinct_id2_ws
