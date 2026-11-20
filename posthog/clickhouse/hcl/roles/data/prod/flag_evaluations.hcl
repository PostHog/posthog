# Prod data nodes read flag evaluations through the flags cluster. They do not store them.
database "posthog" {
  patch_table "flag_evaluations" {
    engine "distributed" {
      cluster_name    = "flags"
      remote_database = "posthog"
      remote_table    = "sharded_flag_evaluations"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }
}
