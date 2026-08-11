# prod-us deltas to base logs objects.
database "posthog" {
  patch_table "kafka_logs_avro" {
    engine "kafka" {
      broker_list          = "warpstream_logs"
      topic_list           = "kafka_topic_list = 'clickhouse_logs'"
      group_name           = "kafka_group_name = 'clickhouse-logs-avro-new'"
      format               = "kafka_format = 'Avro'"
      num_consumers        = 32
      skip_broken_messages = 100
      poll_timeout_ms      = 3000
      poll_max_batch_size  = 1000
      thread_per_consumer  = true
    }
  }
  patch_table "logs34" {
    settings = {
      map_buckets_strategy = "constant"
      max_buckets_in_map   = "32"
    }
  }
  patch_table "trace_spans_kafka_metrics" {
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/logs/{shard}/posthog.trace_spans_kafka_metrics"
      replica_name = "{replica}"
    }
  }
}
