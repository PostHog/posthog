# The apm metrics4 chain, pointed at the metrics cluster. The consumer group has to differ from
# apm's: sharing it would split the topic's partitions between the clusters instead of writing
# every row to both.
database "posthog" {
  patch_table "kafka_metrics_avro4" {
    engine "kafka" {
      collection           = "warpstream_metrics"
      topic_list           = "clickhouse_metrics"
      group_name           = "clickhouse-metrics-avro4-metrics"
      format               = "Avro"
      num_consumers        = 4
      max_block_size       = 1000000
      skip_broken_messages = 100
      poll_timeout_ms      = 3000
      poll_max_batch_size  = 1000
      flush_interval_ms    = 30000
      thread_per_consumer  = true
    }
    settings = {
      input_format_avro_allow_missing_fields = "1"
    }
  }

  patch_table "writable_metrics4_samples" {
    engine "distributed" {
      cluster_name    = "metrics"
      remote_database = "posthog"
      remote_table    = "metrics4_samples"
    }
  }

  patch_table "writable_metrics4_series" {
    engine "distributed" {
      cluster_name    = "metrics"
      remote_database = "posthog"
      remote_table    = "metrics4_series"
    }
  }

  patch_table "writable_metrics4_names" {
    engine "distributed" {
      cluster_name    = "metrics"
      remote_database = "posthog"
      remote_table    = "metrics4_names"
    }
  }

  patch_table "writable_metrics4_attributes" {
    engine "distributed" {
      cluster_name    = "metrics"
      remote_database = "posthog"
      remote_table    = "metrics4_attributes"
    }
  }

  patch_table "writable_metrics_kafka_metrics" {
    engine "distributed" {
      cluster_name    = "metrics"
      remote_database = "posthog"
      remote_table    = "metrics_kafka_metrics"
    }
  }
}
