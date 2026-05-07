CREATE TABLE IF NOT EXISTS `default`.kafka_events_plugin_ingestion_overflow_partition_statistics ON CLUSTER 'posthog'
            (
                `uuid` String,
                `distinct_id` String,
                `ip` String,
                `site_url` String,
                `data` String,
                `team_id` Int64,
                `now` String,
                `sent_at` String,
                `token` String
            )
            ENGINE=Kafka('kafka:9092', 'events_plugin_ingestion_overflow', 'partition_statistics', 'JSONEachRow')
            SETTINGS input_format_values_interpret_expressions=0, kafka_skip_broken_messages = 100
