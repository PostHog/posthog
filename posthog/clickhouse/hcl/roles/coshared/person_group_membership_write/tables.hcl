database "posthog" {
  table "writable_person_group_membership" {
    extend = "_person_group_membership"
    engine "distributed" {
      cluster_name = "aux"
      remote_database = "posthog"
      remote_table = "sharded_person_group_membership"
      sharding_key = "sipHash64(team_id, group_type_index, group_key)"
    }
  }

  dictionary "person_group_membership_config_dict" {
    primary_key = ["team_id"]
    lifetime {
      min = 60
      max = 120
    }
    attribute "team_id" {
      type = "Int64"
    }
    attribute "group_type_index" {
      type = "UInt8"
      default = "255"
    }
    attribute "enabled" {
      type = "UInt8"
      default = "0"
    }
    source "clickhouse" {
      user = "dict_reader"
      query = "SELECT team_id, config.1 AS group_type_index, config.2 AS enabled FROM (SELECT team_id, argMax(tuple(group_type_index, enabled), version) AS config FROM posthog.distributed_person_group_membership_config GROUP BY team_id) WHERE enabled = 1 AND group_type_index <= 4"
    }
    layout "complex_key_hashed" {
    }
  }
}
