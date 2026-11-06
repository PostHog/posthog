# dev force-merges metrics4_samples, matching what its logs cluster runs.
database "posthog" {
  patch_table "metrics4_samples" {
    settings = {
      enable_max_bytes_limit_for_min_age_to_force_merge = "1"
      min_age_to_force_merge_seconds                    = "21600"
    }
  }
}
