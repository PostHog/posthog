# prod-us deltas to shared aux objects.
database "posthog" {
  patch_table "kafka_hog_invocation_results" {
    engine "kafka" {
      broker_list          = "warpstream_cyclotron"
      topic_list           = "kafka_topic_list = 'clickhouse_hog_invocation_results'"
      group_name           = "kafka_group_name = 'clickhouse_hog_invocation_results'"
      format               = "kafka_format = 'JSONEachRow'"
      num_consumers        = 1
      max_block_size       = 100000
      skip_broken_messages = 100
      poll_timeout_ms      = 10000
      thread_per_consumer  = true
    }
  }
}
