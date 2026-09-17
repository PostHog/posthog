# prod-us sessions deltas.
database "posthog" {
  # prod-us runs this table hot: it throttles inserts and merges, and turns off
  # replicated deduplication.
  patch_table "raw_sessions_v3" {
    settings = {
      max_replicated_merges_in_queue                    = "5"
      parts_to_delay_insert                             = "1500"
      parts_to_throw_insert                             = "2000"
      prefer_fetch_merged_part_size_threshold           = "1"
      prefer_fetch_merged_part_time_threshold           = "0"
      replicated_deduplication_window                   = "0"
      replicated_deduplication_window_for_async_inserts = "0"
    }
  }
}
