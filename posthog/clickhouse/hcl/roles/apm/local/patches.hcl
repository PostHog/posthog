database "posthog" {
  patch_table "kafka_metrics_avro4" {
    engine "kafka" {
      collection           = "warpstream_metrics"
      topic_list           = "clickhouse_metrics"
      group_name           = "clickhouse-metrics-avro4"
      format               = "Avro"
      num_consumers        = 1
      skip_broken_messages = 100
      poll_timeout_ms      = 3000
      poll_max_batch_size  = 1000
      thread_per_consumer  = true
    }
    settings = {
      input_format_avro_allow_missing_fields = "1"
    }
  }
}
