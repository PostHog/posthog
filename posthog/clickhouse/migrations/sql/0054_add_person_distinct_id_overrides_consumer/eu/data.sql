CREATE TABLE IF NOT EXISTS kafka_person_distinct_id_overrides ON CLUSTER 'posthog'
(
    team_id Int64,
    distinct_id VARCHAR,
    person_id UUID,
    is_deleted Int8,
    version Int64
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_person_distinct_id', kafka_group_name = 'clickhouse-person-distinct-id-overrides', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS person_distinct_id_overrides_mv 
TO person_distinct_id_overrides
AS SELECT
team_id,
distinct_id,
person_id,
is_deleted,
version,
_timestamp,
_offset,
_partition
FROM kafka_person_distinct_id_overrides
WHERE version > 0 -- only store updated rows, not newly inserted ones
