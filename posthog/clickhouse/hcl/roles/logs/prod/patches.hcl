# Both-prods deltas to base logs objects.
database "posthog" {
  patch_table "logs34" {
    settings = {
      storage_policy = "s3_tiered"
    }
  }
  patch_table "metrics" {
    modify_column "value" {
      type  = "Float64"
      codec = "Gorilla(8)"
    }
    modify_column "count" {
      type    = "UInt64"
      default = "1"
      codec   = "T64"
    }
  }
  patch_table "metrics1" {
    modify_column "value" {
      type  = "Float64"
      codec = "Gorilla(8)"
    }
    modify_column "count" {
      type    = "UInt64"
      default = "1"
      codec   = "T64"
    }
  }
  patch_table "trace_attributes" {
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/logs/{shard}/posthog.trace_attributes"
      replica_name = "{replica}"
    }
  }
  # Both prods kept the original span-count projection and added the is_root_span
  # cut alongside it; local and dev carry the is_root_span cut under the original
  # name instead.
  patch_table "trace_spans" {
    projection "projection_aggregate_counts" {
      query = <<SQL
SELECT
  team_id,
  time_bucket,
  toStartOfMinute(timestamp),
  service_name,
  resource_fingerprint,
  count() AS event_count
GROUP BY
  team_id, time_bucket, toStartOfMinute(timestamp), service_name, resource_fingerprint
SQL

    }
    projection "projection_index_trace_id" {
      query = <<SQL
SELECT _part_offset
ORDER BY trace_id
SQL

      settings = {
        index_granularity = "512"
      }
    }
    projection "projection_aggregate_counts2" {
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
  team_id, time_bucket, toStartOfMinute(timestamp), service_name, is_root_span, resource_fingerprint
SQL

    }
  }
  patch_table "trace_attributes_distributed" {
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "trace_attributes"
    }
  }
}
