database "posthog" {
  table "kafka_hog_invocation_results" {
    column "team_id" {
      type = "Int64"
    }
    column "function_kind" {
      type = "LowCardinality(String)"
    }
    column "function_id" {
      type = "String"
    }
    column "invocation_id" {
      type = "String"
    }
    column "parent_run_id" {
      type = "String"
    }
    column "status" {
      type = "LowCardinality(String)"
    }
    column "attempts" {
      type = "UInt8"
    }
    column "is_retry" {
      type = "UInt8"
    }
    column "scheduled_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "first_scheduled_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "started_at" {
      type = "Nullable(DateTime64(6, 'UTC'))"
    }
    column "finished_at" {
      type = "Nullable(DateTime64(6, 'UTC'))"
    }
    column "duration_ms" {
      type = "Nullable(UInt32)"
    }
    column "error_kind" {
      type = "LowCardinality(String)"
    }
    column "error_message" {
      type = "String"
    }
    column "event_uuid" {
      type = "String"
    }
    column "distinct_id" {
      type = "String"
    }
    column "person_id" {
      type = "String"
    }
    column "invocation_globals" {
      type = "String"
    }
    column "version" {
      type = "UInt64"
    }
    column "is_deleted" {
      type = "UInt8"
    }
    engine "kafka" {
      broker_list          = "warpstream_cyclotron"
      topic_list           = "kafka_topic_list = 'clickhouse_hog_invocation_results'"
      group_name           = "kafka_group_name = 'clickhouse_hog_invocation_results'"
      format               = "kafka_format = 'JSONEachRow'"
      skip_broken_messages = 100
    }
  }
}
