# prod-eu deltas to coshared base objects.
database "posthog" {
  patch_table "sharded_tophog" {
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/ops/{shard}/posthog.tophog"
      replica_name = "{replica}"
    }
  }
}
