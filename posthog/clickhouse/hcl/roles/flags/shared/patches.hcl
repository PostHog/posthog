# The flags cluster is one shard with replicas. Its Kafka consumers and its storage tables
# share a host, so the MVs write straight into the storage tables and there is no
# writable_flag_evaluations proxy. Both the sharded_flag_evaluations and the
# sharded_flag_evaluations_json consumers run four threads under their own groups.
database "posthog" {
  patch_table "sharded_flag_evaluations" {
    settings = {
      storage_policy = "s3_tiered"
    }
  }

  patch_table "sharded_flag_evaluations_json" {
    settings = {
      storage_policy = "s3_tiered"
    }
  }

  patch_table "kafka_flag_evaluations" {
    engine "kafka" {
      collection           = "warpstream_ingestion"
      topic_list           = "clickhouse_flag_evaluations"
      group_name           = "clickhouse_flag_evaluations_flags"
      format               = "JSONEachRow"
      num_consumers        = 4
      max_block_size       = 10000
      skip_broken_messages = 100
      poll_timeout_ms      = 10000
      poll_max_batch_size  = 10000
      flush_interval_ms    = 7500
      thread_per_consumer  = true
    }
  }

  patch_materialized_view "flag_evaluations_mv" {
    to_table = "posthog.sharded_flag_evaluations"
  }

  patch_table "kafka_flag_evaluations_json" {
    engine "kafka" {
      collection           = "warpstream_ingestion"
      topic_list           = "clickhouse_flag_evaluations"
      group_name           = "clickhouse_flag_evaluations_json_flags"
      format               = "JSONEachRow"
      num_consumers        = 4
      max_block_size       = 10000
      skip_broken_messages = 100
      poll_timeout_ms      = 10000
      poll_max_batch_size  = 10000
      flush_interval_ms    = 7500
      thread_per_consumer  = true
    }
  }

  patch_materialized_view "flag_evaluations_json_mv" {
    to_table = "posthog.sharded_flag_evaluations_json"
  }
}
