database "posthog" {
  table "distributed_person_group_membership_config" {
    extend = "_person_group_membership_config"
    engine "distributed" {
      cluster_name = "aux"
      remote_database = "posthog"
      remote_table = "person_group_membership_config"
      sharding_key = "sipHash64(team_id)"
    }
  }
}
