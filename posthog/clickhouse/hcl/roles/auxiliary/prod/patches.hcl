# Both-prods deltas to shared aux objects.
database "posthog" {
  patch_table "hog_invocation_results_data" {
    settings = {
      storage_policy = "s3_tiered"
    }
  }
  patch_table "log_entries_data" {
    ttl = "toDate(timestamp) + toIntervalDay(7) TO VOLUME 'cold', toDate(timestamp) + toIntervalDay(90)"
    settings = {
      storage_policy = "s3_tiered"
    }
  }
  # Cloud stores raw_sessions on the sessions satellite, not behind the data cluster.
  patch_table "raw_sessions" {
    engine "distributed" {
      cluster_name    = "sessions"
      remote_database = "posthog"
      remote_table    = "raw_sessions"
      sharding_key    = "cityHash64(session_id_v7)"
    }
  }
}
