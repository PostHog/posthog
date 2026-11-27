# One row per bucket of a precomputed metric, written by the metrics precompute fill.
# posthog/clickhouse/metrics/precomputed_buckets.py defines the source schema.
database "posthog" {
  table "metrics_precomputed_buckets" {
    order_by     = ["team_id", "precomputed_metric_id", "bucket_start"]
    partition_by = "toDate(bucket_start)"
    ttl          = "bucket_start + toIntervalDay(32)"
    settings = {
      index_granularity   = "128"
      ttl_only_drop_parts = "1"
    }
    column "team_id" {
      type = "Int32"
    }
    column "precomputed_metric_id" {
      type = "UUID"
    }
    column "bucket_start" {
      type = "DateTime"
    }
    column "final" {
      type = "Bool"
    }
    column "written_at" {
      type = "DateTime64(6)"
    }
    column "entry_labels" {
      type = "Array(Array(String))"
    }
    column "entry_metric_types" {
      type = "Array(LowCardinality(String))"
    }
    column "entry_bounds" {
      type = "Array(Array(Float64))"
    }
    column "entry_values" {
      type = "Array(Float64)"
    }
    column "entry_counts" {
      type = "Array(Array(Float64))"
    }
    column "entry_fingerprints" {
      type = "Array(Array(UInt64))"
    }
    column "entry_fingerprints_truncated" {
      type = "Array(Bool)"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.metrics_precomputed_buckets"
      replica_name   = "{replica}-{shard}"
      version_column = "written_at"
    }
  }
}
