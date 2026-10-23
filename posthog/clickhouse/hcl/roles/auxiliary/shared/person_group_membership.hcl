database "posthog" {
  table "sharded_person_group_membership" {
    extend = "_person_group_membership"
    order_by = ["team_id", "group_type_index", "group_key", "distinct_id"]
    index "idx_distinct_id" {
      expr        = "distinct_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    settings = {
      index_granularity = "8192"
      min_rows_for_wide_part = "0"
      min_bytes_for_wide_part = "0"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path = "/clickhouse/tables/{shard}/posthog.sharded_person_group_membership"
      replica_name = "{replica}"
    }
  }

  table "person_group_membership_config" {
    extend = "_person_group_membership_config"
    order_by = ["team_id"]
    settings = {
      index_granularity = "8192"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path = "/clickhouse/tables/noshard/posthog.person_group_membership_config"
      replica_name = "{replica}-{shard}"
      version_column = "version"
    }
  }
}
