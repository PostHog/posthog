database "posthog" {
  patch_dictionary "person_group_membership_config_dict" {
    source "clickhouse" {
      user = "default"
      query = "SELECT team_id, config.1 AS group_type_index, config.2 AS enabled FROM (SELECT team_id, argMax(tuple(group_type_index, enabled), version) AS config FROM posthog.distributed_person_group_membership_config GROUP BY team_id) WHERE enabled = 1 AND group_type_index <= 4"
    }
  }
}
