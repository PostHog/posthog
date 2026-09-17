# dev deltas to shared aux objects: identical pipeline, property_values Kafka
# consumer downsized for dev volume (the canonical definition runs 8).
database "posthog" {
  patch_table "kafka_property_values" {
    engine "kafka" {
      collection          = "warpstream_ingestion"
      topic_list          = "clickhouse_property_values"
      group_name          = "clickhouse_property_values"
      format              = "JSONEachRow"
      num_consumers       = 1
      thread_per_consumer = true
    }
  }
}
