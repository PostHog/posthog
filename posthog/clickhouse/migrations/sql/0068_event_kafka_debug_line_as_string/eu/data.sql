DROP TABLE IF EXISTS `default`.kafka_clickhouse_events_json_debug ON CLUSTER 'posthog'

CREATE TABLE IF NOT EXISTS `default`.kafka_clickhouse_events_json_debug ON CLUSTER 'posthog'
      (
        payload String
      )
      ENGINE=Kafka('kafka:9092', 'clickhouse_events_json', 'debug', 'LineAsString')
      SETTINGS input_format_values_interpret_expressions=0, kafka_handle_error_mode='stream'

DROP TABLE IF EXISTS `default`.clickhouse_events_json_debug_mv ON CLUSTER 'posthog' SYNC

CREATE MATERIALIZED VIEW IF NOT EXISTS `default`.clickhouse_events_json_debug_mv ON CLUSTER 'posthog' TO clickhouse_events_json_debug
      AS SELECT
        payload,
        _timestamp,
        _timestamp_ms,
        _partition,
        _offset,
        _error,
        _raw_message
      FROM `default`.kafka_clickhouse_events_json_debug
