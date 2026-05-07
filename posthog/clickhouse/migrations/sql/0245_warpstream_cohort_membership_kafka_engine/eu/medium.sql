CREATE TABLE IF NOT EXISTS kafka_cohort_membership_ws
(
    `team_id` Int64,
    `cohort_id` Int64,
    `person_id` UUID,
    `status` Enum8('entered' = 1, 'left' = 2, 'member' = 3, 'not_member' = 4),
    `last_updated` DateTime64(6)
) ENGINE = Kafka(warpstream_calculated_events, kafka_topic_list = 'cohort_membership_changed', kafka_group_name = 'clickhouse_cohort_membership_ws', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS cohort_membership_ws_mv TO writable_cohort_membership
AS SELECT
    team_id,
    cohort_id,
    person_id,
    multiIf(status = 'member', 'entered', status = 'not_member', 'left', status) AS status,
    last_updated
FROM kafka_cohort_membership_ws
