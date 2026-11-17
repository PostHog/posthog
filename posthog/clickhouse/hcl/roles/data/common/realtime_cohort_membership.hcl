database "posthog" {
  table "realtime_cohort_membership" {
    order_by = ["team_id", "cohort_id", "kind", "person_id", "floor_run_id", "floor_partition"]
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "Int64"
    }
    column "cohort_id" {
      type = "Int64"
    }
    column "kind" {
      type = "Enum8('member'=0, 'floor'=1)"
    }
    column "person_id" {
      type = "UUID"
    }
    column "floor_run_id" {
      type = "UUID"
    }
    column "floor_partition" {
      type = "UInt16"
    }
    column "in_cohort" {
      type = "UInt8"
    }
    column "version" {
      type = "DateTime64(6, 'UTC')"
    }
    column "floor_partitions" {
      type = "UInt16"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.realtime_cohort_membership"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }
}
