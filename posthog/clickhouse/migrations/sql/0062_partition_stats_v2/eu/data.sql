CREATE TABLE IF NOT EXISTS `default`.events_plugin_ingestion_partition_statistics_v2 ON CLUSTER 'posthog' (
                topic LowCardinality(String),
                partition UInt64,
                offset UInt64,
                token String,
                distinct_id String,
                ip Tuple(v4 IPv4, v6 IPv6),
                event String,
                data_length UInt64,
                timestamp DateTime
            )
            ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.events_plugin_ingestion_partition_statistics_v2', '{replica}-{shard}', timestamp)
            PARTITION BY (topic, toStartOfDay(timestamp))
            ORDER BY (topic, partition, offset)
            TTL timestamp + INTERVAL 30 DAY

CREATE MATERIALIZED VIEW IF NOT EXISTS `default`.events_plugin_ingestion_partition_statistics_v2_mv ON CLUSTER 'posthog'
            TO `default`.events_plugin_ingestion_partition_statistics_v2
            AS SELECT
                _topic AS topic,
                _partition AS partition,
                _offset AS offset,
                token,
                distinct_id,
                (toIPv4OrDefault(kafka_table.ip), toIPv6OrDefault(kafka_table.ip)) AS ip,
                JSONExtractString(data, 'event') AS event,
                length(data) AS data_length,
                _timestamp AS timestamp
            FROM default.kafka_events_plugin_ingestion_partition_statistics AS kafka_table

CREATE MATERIALIZED VIEW IF NOT EXISTS `default`.events_plugin_ingestion_overflow_partition_statistics_v2_mv ON CLUSTER 'posthog'
            TO `default`.events_plugin_ingestion_partition_statistics_v2
            AS SELECT
                _topic AS topic,
                _partition AS partition,
                _offset AS offset,
                token,
                distinct_id,
                (toIPv4OrDefault(kafka_table.ip), toIPv6OrDefault(kafka_table.ip)) AS ip,
                JSONExtractString(data, 'event') AS event,
                length(data) AS data_length,
                _timestamp AS timestamp
            FROM default.kafka_events_plugin_ingestion_overflow_partition_statistics AS kafka_table

CREATE TABLE IF NOT EXISTS `default`.kafka_events_plugin_ingestion_historical_partition_statistics ON CLUSTER 'posthog'
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
            ENGINE=Kafka('kafka:9092', 'events_plugin_ingestion_historical', 'partition_statistics', 'JSONEachRow')
            SETTINGS input_format_values_interpret_expressions=0, kafka_skip_broken_messages = 100

CREATE MATERIALIZED VIEW IF NOT EXISTS `default`.events_plugin_ingestion_historical_partition_statistics_v2_mv ON CLUSTER 'posthog'
            TO `default`.events_plugin_ingestion_partition_statistics_v2
            AS SELECT
                _topic AS topic,
                _partition AS partition,
                _offset AS offset,
                token,
                distinct_id,
                (toIPv4OrDefault(kafka_table.ip), toIPv6OrDefault(kafka_table.ip)) AS ip,
                JSONExtractString(data, 'event') AS event,
                length(data) AS data_length,
                _timestamp AS timestamp
            FROM default.kafka_events_plugin_ingestion_historical_partition_statistics AS kafka_table
