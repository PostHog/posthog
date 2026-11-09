# dev runs its consumers smaller than the prod clusters do.
database "posthog" {
  patch_table "kafka_metrics_avro4" {
    engine "kafka" {
      collection           = "warpstream_metrics"
      topic_list           = "clickhouse_metrics"
      group_name           = "clickhouse-metrics-avro4-metrics"
      format               = "Avro"
      num_consumers        = 4
      max_block_size       = 10000
      skip_broken_messages = 100
      poll_timeout_ms      = 3000
      poll_max_batch_size  = 100
      flush_interval_ms    = 3000
      thread_per_consumer  = true
    }
    settings = {
      input_format_avro_allow_missing_fields = "1"
    }
  }
}
