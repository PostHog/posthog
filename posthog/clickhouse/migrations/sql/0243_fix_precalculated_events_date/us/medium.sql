DROP TABLE IF EXISTS precalculated_events_mv

DROP TABLE IF EXISTS precalculated_events_ws_mv

DROP TABLE IF EXISTS kafka_precalculated_events

DROP TABLE IF EXISTS kafka_precalculated_events_ws

CREATE TABLE IF NOT EXISTS kafka_precalculated_events
(
    team_id Int64,
    date Nullable(Date),
    distinct_id String,
    person_id UUID,
    condition String,
    uuid UUID,
    source String
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_prefiltered_events', kafka_group_name = 'clickhouse_precalculated_events2', kafka_format = 'JSONEachRow')
SETTINGS kafka_max_block_size = 1000000, kafka_poll_max_batch_size = 100000, kafka_poll_timeout_ms = 1000, kafka_flush_interval_ms = 7500, kafka_skip_broken_messages = 100, kafka_num_consumers = 1

CREATE MATERIALIZED VIEW IF NOT EXISTS precalculated_events_mv TO writable_precalculated_events
AS SELECT
    team_id,
    ifNull(date, toDate(_timestamp)) AS date,
    distinct_id,
    person_id,
    condition,
    uuid,
    source,
    _timestamp,
    _offset,
    _partition
FROM kafka_precalculated_events

CREATE TABLE IF NOT EXISTS kafka_precalculated_events_ws
(
    team_id Int64,
    date Nullable(Date),
    distinct_id String,
    person_id UUID,
    condition String,
    uuid UUID,
    source String
) ENGINE = Kafka(warpstream_calculated_events, kafka_topic_list = 'clickhouse_prefiltered_events', kafka_group_name = 'clickhouse_precalculated_events_ws', kafka_format = 'JSONEachRow')
SETTINGS kafka_max_block_size = 1000000, kafka_poll_max_batch_size = 100000, kafka_poll_timeout_ms = 1000, kafka_flush_interval_ms = 7500, kafka_skip_broken_messages = 100, kafka_num_consumers = 1

CREATE MATERIALIZED VIEW IF NOT EXISTS precalculated_events_ws_mv TO writable_precalculated_events
AS SELECT
    team_id,
    ifNull(date, toDate(_timestamp)) AS date,
    distinct_id,
    person_id,
    condition,
    uuid,
    source,
    _timestamp,
    _offset,
    _partition
FROM kafka_precalculated_events_ws
