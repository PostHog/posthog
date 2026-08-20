# dev deltas to the prod ai_events stack: identical pipeline, Kafka consumer
# downsized for dev volume (prod runs 16).
database "posthog" {
  patch_table "kafka_ai_events_json_ws" {
    engine "kafka" {
      broker_list          = "warpstream_ingestion"
      topic_list           = "kafka_topic_list = 'clickhouse_ai_events_json'"
      group_name           = "kafka_group_name = 'clickhouse_ai_events_ws'"
      format               = "kafka_format = 'JSONEachRow'"
      num_consumers        = 1
      max_block_size       = 5000
      skip_broken_messages = 100
      poll_timeout_ms      = 10000
      thread_per_consumer  = true
    }
  }
}
