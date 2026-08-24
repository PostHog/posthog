# prod-eu deltas to base logs objects.
database "posthog" {
  patch_table "kafka_logs_avro" {
    column "bytes_uncompressed" {
      type  = "Int64"
      after = "attributes"
    }
    engine "kafka" {
      broker_list          = "warpstream_logs"
      topic_list           = "kafka_topic_list = 'clickhouse_logs'"
      group_name           = "kafka_group_name = 'clickhouse-logs-avro-new'"
      format               = "kafka_format = 'Avro'"
      num_consumers        = 16
      skip_broken_messages = 100
      poll_timeout_ms      = 3000
      poll_max_batch_size  = 1000
      thread_per_consumer  = true
    }
  }
  patch_table "kafka_trace_spans_avro" {
    engine "kafka" {
      broker_list          = "warpstream_traces"
      topic_list           = "kafka_topic_list = 'clickhouse_traces'"
      group_name           = "kafka_group_name = 'clickhouse-traces-avro'"
      format               = "kafka_format = 'Avro'"
      num_consumers        = 2
      skip_broken_messages = 100
      poll_timeout_ms      = 3000
      poll_max_batch_size  = 1000
      thread_per_consumer  = true
    }
  }
  patch_materialized_view "kafka_logs_avro_billing_metrics_mv" {
    query = file("sql/kafka_logs_avro_billing_metrics_mv.sql")
  }
  patch_table "trace_spans_distributed" {
    column "_partition" {
      type = "UInt32"
      after = "links"
    }
    column "_topic" {
      type = "String"
      after = "_partition"
    }
    column "_offset" {
      type = "UInt64"
      after = "_topic"
    }
    column "_bytes_uncompressed" {
      type = "UInt64"
      after = "_offset"
    }
    column "_bytes_compressed" {
      type = "UInt64"
      after = "_bytes_uncompressed"
    }
    column "_record_count" {
      type = "UInt64"
      after = "_bytes_compressed"
    }
  }
}
