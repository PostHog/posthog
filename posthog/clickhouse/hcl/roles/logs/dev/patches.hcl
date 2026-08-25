# dev deltas to base logs objects. logs34 carries the prod storage/settings shape;
# the metrics/metrics1 codec deltas in roles/logs/prod are deliberately not composed
# here (intentional dev divergence).
#
# The trace family sits between the two shapes: dev keeps the single-shard ZK path
# and the three-projection trace_spans the local node runs, but reads through the
# `logs` cluster like both prods.
database "posthog" {
  patch_table "logs34" {
    settings = {
      storage_policy       = "s3_tiered"
      map_buckets_strategy = "constant"
      max_buckets_in_map   = "32"
    }
  }

  # dev batches metrics ingest harder than the prods do.
  patch_table "kafka_metrics_avro" {
    engine "kafka" {
      broker_list          = "warpstream_metrics"
      topic_list           = "kafka_topic_list = 'clickhouse_metrics'"
      group_name           = "kafka_group_name = 'clickhouse-metrics-avro-new'"
      format               = "kafka_format = 'Avro'"
      num_consumers        = 8
      max_block_size       = 65536
      skip_broken_messages = 100
      poll_timeout_ms      = 3000
      poll_max_batch_size  = 65536
      flush_interval_ms    = 7500
      thread_per_consumer  = true
    }
  }

  patch_table "trace_attributes_distributed" {
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "trace_attributes"
    }
  }

  patch_table "trace_spans" {
    projection "projection_aggregate_counts" {
      query = <<SQL
SELECT
  team_id,
  time_bucket,
  toStartOfMinute(timestamp),
  service_name,
  resource_fingerprint,
  is_root_span,
  count() AS event_count
GROUP BY
  team_id, time_bucket, toStartOfMinute(timestamp), service_name, resource_fingerprint, is_root_span
SQL

    }
    projection "projection_index_trace_id" {
      query = <<SQL
SELECT _part_offset
ORDER BY trace_id
SQL

    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.trace_spans"
      replica_name = "{replica}-{shard}"
    }
  }

  patch_materialized_view "kafka_logs34_avro_mv" {
    modify_column "_bytes_uncompressed" {
      type = "Nullable(Float64)"
    }
    modify_column "_bytes_compressed" {
      type = "Nullable(Float64)"
    }
  }
}
