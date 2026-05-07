DROP TABLE IF EXISTS `default`.kafka_clickhouse_events_json_debug ON CLUSTER 'posthog'

DROP TABLE IF EXISTS `default`.clickhouse_events_json_debug_mv ON CLUSTER 'posthog' SYNC

DROP TABLE IF EXISTS `default`.clickhouse_events_json_debug ON CLUSTER 'posthog' SYNC
