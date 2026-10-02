database "posthog" {
  table "person_group_membership" {
    extend = "_person_group_membership"
    engine "distributed" {
      cluster_name = "aux"
      remote_database = "posthog"
      remote_table = "sharded_person_group_membership"
      sharding_key = "sipHash64(team_id, group_type_index, group_key)"
    }
  }
}
