# prod-us deltas to base logs objects.
database "posthog" {
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
