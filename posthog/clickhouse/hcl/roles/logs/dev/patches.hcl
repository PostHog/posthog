# dev deltas to base logs objects. logs34 carries the prod storage/settings shape;
# the metrics/metrics1 codec and trace-family ZK-path deltas in roles/logs/prod are
# deliberately not composed here (intentional dev divergence).
database "posthog" {
  patch_table "logs34" {
    settings = {
      storage_policy       = "s3_tiered"
      map_buckets_strategy = "constant"
      max_buckets_in_map   = "32"
    }
  }
}
