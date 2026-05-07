CREATE TABLE IF NOT EXISTS kafka_person_distinct_id_overrides_ws 
(
    team_id Int64,
    distinct_id VARCHAR,
    person_id UUID,
    is_deleted Int8,
    version Int64
    
) ENGINE = Kafka(warpstream_ingestion, kafka_topic_list = 'clickhouse_person_distinct_id', kafka_group_name = 'clickhouse_person_distinct_id_overrides_ws', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS person_distinct_id_overrides_ws_mv 
TO writable_person_distinct_id_overrides
AS SELECT
team_id,
distinct_id,
person_id,
is_deleted,
version,
_timestamp,
_offset,
_partition
FROM kafka_person_distinct_id_overrides_ws
WHERE version > 0 -- only store updated rows, not newly inserted ones
