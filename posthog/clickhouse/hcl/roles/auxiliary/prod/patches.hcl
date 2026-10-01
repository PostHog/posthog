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
}
