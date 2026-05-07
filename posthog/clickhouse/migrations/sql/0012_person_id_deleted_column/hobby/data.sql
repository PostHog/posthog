DROP TABLE IF EXISTS person_distinct_id_mv

DROP TABLE IF EXISTS kafka_person_distinct_id

ALTER TABLE person_distinct_id ADD COLUMN IF NOT EXISTS is_deleted Int8 DEFAULT 0

CREATE TABLE IF NOT EXISTS kafka_person_distinct_id ON CLUSTER 'posthog'
(
    distinct_id VARCHAR,
    person_id UUID,
    team_id Int64,
    _sign Nullable(Int8),
    is_deleted Nullable(Int8)
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_person_unique_id', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS person_distinct_id_mv ON CLUSTER 'posthog'
TO default.person_distinct_id
AS SELECT
distinct_id,
person_id,
team_id,
coalesce(_sign, if(is_deleted==0, 1, -1)) AS _sign,
_timestamp,
_offset
FROM default.kafka_person_distinct_id
