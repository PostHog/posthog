# prod-eu deltas to coshared base objects.
database "posthog" {
  patch_table "sharded_events_recent" {
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/batch_exports/{shard}/posthog.sharded_events_recent"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }
}
