# prod-us deltas to base objects.
database "posthog" {
  # prod-eu dropped the partition when the table was rebuilt there; prod-us has
  # not been rebuilt yet.
  patch_table "query_team_daily_stats" {
    partition_by = "analysis_date"
  }

  patch_table "sharded_tophog" {
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/ops/{shard}/posthog.tophog_new"
      replica_name = "{replica}"
    }
  }
}
