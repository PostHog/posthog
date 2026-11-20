# prod-us deltas to base logs objects.
database "posthog" {
  patch_table "logs34" {
    settings = {
      map_buckets_strategy = "constant"
      max_buckets_in_map   = "32"
    }
  }
}
