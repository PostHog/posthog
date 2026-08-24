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
  patch_table "trace_attributes_distributed" {
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "trace_attributes"
    }
  }
}
