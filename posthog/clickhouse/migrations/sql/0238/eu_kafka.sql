CREATE TABLE IF NOT EXISTS posthog.kafka_events_json_ws
(
    `uuid` UUID,
    `event` String,
    `properties` String,
    `timestamp` DateTime64(6, 'UTC'),
    `team_id` Int64,
    `distinct_id` String,
    `elements_chain` String,
    `created_at` DateTime64(6, 'UTC'),
    `person_id` UUID,
    `person_created_at` DateTime64(3),
    `person_properties` String,
    `group0_properties` String,
    `group1_properties` String,
    `group2_properties` String,
    `group3_properties` String,
    `group4_properties` String,
    `group0_created_at` DateTime64(3),
    `group1_created_at` DateTime64(3),
    `group2_created_at` DateTime64(3),
    `group3_created_at` DateTime64(3),
    `group4_created_at` DateTime64(3),
    `person_mode` Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2),
    `historical_migration` Bool
)
ENGINE = Kafka(warpstream_ingestion, kafka_topic_list = 'clickhouse_events_json', kafka_group_name = 'clickhouse_events_json_ws', kafka_format = 'JSONEachRow')
SETTINGS kafka_skip_broken_messages = 100, kafka_num_consumers = 1, kafka_thread_per_consumer = 1
