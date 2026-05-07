DROP TABLE IF EXISTS kafka_behavioral_cohorts_matches

DROP TABLE IF EXISTS behavioral_cohorts_matches_mv

CREATE TABLE IF NOT EXISTS kafka_precalculated_events
(
    team_id Int64,
    date Nullable(Date),
    distinct_id String,
    person_id UUID,
    condition String,
    uuid UUID,
    source String
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_prefiltered_events', kafka_group_name = 'clickhouse_prefiltered_events', kafka_format = 'JSONEachRow')
SETTINGS kafka_max_block_size = 1000000, kafka_poll_max_batch_size = 100000, kafka_poll_timeout_ms = 1000, kafka_flush_interval_ms = 7500, kafka_skip_broken_messages = 100, kafka_num_consumers = 1

CREATE TABLE IF NOT EXISTS writable_precalculated_events
(
    team_id Int64,
    date Date,
    distinct_id String,
    person_id UUID,
    condition String,
    uuid UUID,
    source String,
    _timestamp DateTime64(6),
    _partition UInt64,
    _offset UInt64
) ENGINE = Distributed('posthog', 'default', 'sharded_precalculated_events', sipHash64(distinct_id))

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

CREATE TABLE IF NOT EXISTS writable_cohort_membership
(
    team_id Int64,
    cohort_id Int64,
    person_id UUID,
    status Enum8('entered' = 1, 'left' = 2),
    last_updated DateTime64(6) DEFAULT now64()
) ENGINE = Distributed('posthog_single_shard', 'default', 'cohort_membership')

CREATE TABLE IF NOT EXISTS kafka_cohort_membership
(
    `team_id` Int64,
    `cohort_id` Int64,
    `person_id` UUID,
    `status` Enum8('entered' = 1, 'left' = 2, 'member' = 3, 'not_member' = 4),
    `last_updated` DateTime64(6)
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'cohort_membership_changed', kafka_group_name = 'clickhouse_cohort_membership_changed', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS cohort_membership_mv TO writable_cohort_membership
AS SELECT
    team_id,
    cohort_id,
    person_id,
    multiIf(status = 'member', 'entered', status = 'not_member', 'left', status) AS status,
    last_updated
FROM kafka_cohort_membership
