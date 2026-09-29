database "posthog" {
  table "kafka_person_group_membership" {
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "properties" {
      type = "String"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    engine "kafka" {
      collection           = "warpstream_ingestion"
      topic_list           = "clickhouse_events_json"
      group_name           = "clickhouse_person_group_membership"
      format               = "JSONEachRow"
      num_consumers        = 1
      skip_broken_messages = 100
      thread_per_consumer  = true
      poll_timeout_ms      = 10000
      max_block_size       = 100000
    }
  }

  materialized_view "person_group_membership_mv" {
    to_table = "posthog.writable_person_group_membership"
    column "team_id" {
      type = "Int64"
    }
    column "group_type_index" {
      type = "UInt8"
    }
    column "group_key" {
      type = "String"
    }
    column "distinct_id" {
      type = "String"
    }
    column "first_seen" {
      type = "DateTime64(6, 'UTC')"
    }
    column "last_seen" {
      type = "DateTime64(6, 'UTC')"
    }
    query = file("sql/person_group_membership_mv.sql")
  }
}
