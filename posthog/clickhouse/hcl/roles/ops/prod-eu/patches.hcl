# prod-eu deltas to base objects.
database "posthog" {
  # No tiered storage here, unlike dev and prod-us; the archive is kept in check
  # with merge and insert throttling instead.
  patch_table "sharded_query_log_archive" {
    settings = {
      max_replicated_merges_in_queue          = "6"
      parts_to_delay_insert                   = "1000"
      parts_to_throw_insert                   = "3000"
      prefer_fetch_merged_part_size_threshold = "1"
      prefer_fetch_merged_part_time_threshold = "60"
    }
  }

  patch_table "sharded_tophog" {
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/ops/{shard}/posthog.tophog"
      replica_name = "{replica}"
    }
  }
}
