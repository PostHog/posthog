# Ops analytics rollups, prod only. dev does not run the job that fills them.
database "posthog" {
  table "query_team_daily_stats" {
    order_by = ["analysis_date", "team_id"]
    ttl      = "analysis_date + toIntervalDay(90)"
    settings = {
      index_granularity = "8192"
    }
    column "analysis_date" {
      type = "Date"
    }
    column "team_id" {
      type = "Int64"
    }
    column "query_count" {
      type = "UInt64"
    }
    column "error_count" {
      type = "UInt64"
    }
    column "distinct_query_shapes" {
      type = "UInt64"
    }
    column "total_duration_ms" {
      type = "UInt64"
    }
    column "avg_duration_ms" {
      type = "Float64"
    }
    column "p50_duration_ms" {
      type = "Float64"
    }
    column "p90_duration_ms" {
      type = "Float64"
    }
    column "p99_duration_ms" {
      type = "Float64"
    }
    column "max_duration_ms" {
      type = "UInt64"
    }
    column "total_read_rows" {
      type = "UInt64"
    }
    column "total_read_bytes" {
      type    = "UInt64"
      comment = "Uncompressed bytes scanned, coordinator-side summed across shards (is_initial_query=1). Compute/scan cost proxy, NOT stored footprint."
    }
    column "total_result_rows" {
      type = "UInt64"
    }
    column "total_result_bytes" {
      type = "UInt64"
    }
    column "total_written_rows" {
      type = "UInt64"
    }
    column "total_written_bytes" {
      type = "UInt64"
    }
    column "total_cpu_seconds" {
      type    = "Float64"
      comment = "ProfileEvents OSCPUVirtualTimeMicroseconds summed across ALL QueryFinish rows (initiator + shard leaves) / 1e6. CPU is not folded onto the initiator row, so leaves must be summed."
    }
    column "total_memory_usage" {
      type    = "UInt64"
      comment = "Peak memory_usage summed across all shard rows (per-node peak; not folded onto the initiator)."
    }
    column "max_memory_usage" {
      type    = "UInt64"
      comment = "Largest single-node peak memory across all shard rows."
    }
    column "p99_memory_usage" {
      type = "Float64"
    }
    column "total_s3_get_objects" {
      type    = "UInt64"
      comment = "ProfileEvents S3GetObject summed across all shard rows: object-storage GET count."
    }
    column "total_s3_read_bytes" {
      type    = "UInt64"
      comment = "ProfileEvents ReadBufferFromS3Bytes summed across all shard rows: object-storage read cost proxy."
    }
    column "query_kind_counts" {
      type    = "Map(String, UInt64)"
      comment = "query_kind -> count for QueryFinish rows."
    }
    column "computed_at" {
      type = "DateTime"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/ops/tables/{shard}/posthog.query_team_daily_stats"
      replica_name = "{replica}"
    }
  }
}
