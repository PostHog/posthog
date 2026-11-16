# dev deltas to base objects. dev tracks prod-us on all three: it is where the
# prod-us experiments are tried first.
database "posthog" {
  patch_table "sharded_tophog" {
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/ops/{shard}/posthog.tophog_new"
      replica_name = "{replica}"
    }
  }
}
