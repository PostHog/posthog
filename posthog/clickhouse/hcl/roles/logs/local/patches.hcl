# Local-node deltas to the trace-spans suite: the single-shard local cluster in
# place of the logs cluster, and the kafka meta columns on the distributed reader.
database "posthog" {
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
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "trace_spans"
    }
  }
}
