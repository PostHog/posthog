DROP TABLE IF EXISTS precalculated_person_properties_mv

DROP TABLE IF EXISTS kafka_precalculated_person_properties

DROP TABLE IF EXISTS writable_precalculated_person_properties

CREATE TABLE IF NOT EXISTS writable_precalculated_person_properties
(
    team_id Int64,
    distinct_id String,
    person_id UUID,
    condition String,
    matches Bool,
    source String,
    _timestamp DateTime64(6),
    _offset UInt64
) ENGINE = Distributed('posthog', 'default', 'sharded_precalculated_person_properties', sipHash64(distinct_id))

CREATE TABLE IF NOT EXISTS kafka_precalculated_person_properties
(
    team_id Int64,
    distinct_id String,
    person_id UUID,
    condition String,
    matches Bool,
    source String
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_precalculated_person_properties', kafka_group_name = 'clickhouse_precalculated_person_properties2', kafka_format = 'JSONEachRow')
SETTINGS kafka_max_block_size = 1000000, kafka_poll_max_batch_size = 100000, kafka_poll_timeout_ms = 1000, kafka_flush_interval_ms = 7500, kafka_skip_broken_messages = 100, kafka_num_consumers = 1

CREATE MATERIALIZED VIEW IF NOT EXISTS precalculated_person_properties_mv TO writable_precalculated_person_properties
AS SELECT
    team_id,
    distinct_id,
    person_id,
    condition,
    matches,
    source,
    _timestamp,
    _offset
FROM kafka_precalculated_person_properties
