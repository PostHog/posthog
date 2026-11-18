# prod-us deltas to shared aux objects.
database "posthog" {
  patch_table "kafka_hog_invocation_results" {
    engine "kafka" {
      collection           = "warpstream_cyclotron"
      topic_list           = "clickhouse_hog_invocation_results"
      group_name           = "clickhouse_hog_invocation_results"
      format               = "JSONEachRow"
      num_consumers        = 1
      max_block_size       = 100000
      skip_broken_messages = 100
      poll_timeout_ms      = 10000
      thread_per_consumer  = true
    }
  }
}
