# Both-prods deltas to shared aux objects.
database "posthog" {
  patch_table "hog_invocation_results_data" {
    settings = {
      storage_policy = "s3_tiered"
    }
  }
}
