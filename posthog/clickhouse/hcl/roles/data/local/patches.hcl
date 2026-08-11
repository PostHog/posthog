# Local data-node deltas to the coshared sessions/ai_events bases: the storage
# attributes of the tables this node owns (the satellites read them through
# Distributed proxies or keep their own replicas).
database "posthog" {
  patch_table "cohortpeople" {
    order_by = ["team_id", "cohort_id", "person_id", "version"]
    settings = {
      index_granularity = "8192"
    }
    engine "replicated_collapsing_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.cohortpeople"
      replica_name = "{replica}-{shard}"
      sign_column  = "sign"
    }
  }

  patch_table "person_distinct_id_overrides" {
    order_by = ["team_id", "distinct_id"]
    settings = {
      index_granularity = "512"
    }
    index "kafka_timestamp_minmax_person_distinct_id_overrides" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.person_distinct_id_overrides"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }

  patch_table "person_static_cohort" {
    order_by = ["team_id", "cohort_id", "person_id", "id"]
    settings = {
      index_granularity = "8192"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.person_static_cohort"
      replica_name   = "{replica}-{shard}"
      version_column = "_timestamp"
    }
  }

  patch_table "web_pre_aggregated_teams" {
    order_by = ["team_id"]
    settings = {
      index_granularity = "8192"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.web_analytics_team_selection"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }

  patch_table "person" {
    order_by = ["team_id", "id"]
    settings = {
      index_granularity = "8192"
    }
    column "_timestamp" {
      type = "DateTime"
      after = "last_seen_at"
    }
    column "_offset" {
      type = "UInt64"
      after = "_timestamp"
    }
    index "kafka_timestamp_minmax_person" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.person"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }

  patch_table "person_distinct_id2" {
    order_by = ["team_id", "distinct_id"]
    settings = {
      index_granularity = "512"
    }
    column "_timestamp" {
      type = "DateTime"
      after = "version"
    }
    column "_offset" {
      type = "UInt64"
      after = "_timestamp"
    }
    column "_partition" {
      type = "UInt64"
      after = "_offset"
    }
    index "kafka_timestamp_minmax_person_distinct_id2" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.person_distinct_id2"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }

  patch_dictionary "channel_definition_dict" {
    source "clickhouse" {
      user  = "default"
      table = "channel_definition"
    }
  }

  patch_dictionary "web_pre_aggregated_teams_dict" {
    source "clickhouse" {
      user  = "default"
      query = "SELECT     team_id FROM     `posthog`.`web_pre_aggregated_teams` FINAL WHERE version > 0"
    }
  }

  patch_table "events_recent" {
    modify_column "properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    modify_column "person_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    modify_column "group0_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    modify_column "group1_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    modify_column "group2_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    modify_column "group3_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    modify_column "group4_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "historical_migration" {
      type = "Bool"
      after = "person_mode"
    }
    modify_column "inserted_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now64()"
    }
    engine "distributed" {
      cluster_name    = "posthog_primary_replica"
      remote_database = "posthog"
      remote_table    = "sharded_events_recent"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }

  patch_table "sharded_ingestion_warnings" {
    partition_by = "toYYYYMMDD(timestamp)"
    modify_column "details" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.sharded_ingestion_warnings"
      replica_name = "{replica}"
    }
  }
}
