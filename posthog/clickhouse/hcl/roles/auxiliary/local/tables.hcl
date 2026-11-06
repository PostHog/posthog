database "posthog" {
  table "kafka_error_tracking_fingerprint_issue_state" {
    column "team_id" {
      type = "Int64"
    }
    column "fingerprint" {
      type = "String"
    }
    column "issue_id" {
      type = "UUID"
    }
    column "issue_name" {
      type = "Nullable(String)"
    }
    column "issue_description" {
      type = "Nullable(String)"
    }
    column "issue_status" {
      type = "String"
    }
    column "issue_severity" {
      type = "Nullable(String)"
    }
    column "assigned_user_id" {
      type = "Nullable(Int64)"
    }
    column "assigned_role_id" {
      type = "Nullable(UUID)"
    }
    column "first_seen" {
      type = "DateTime64(3, 'UTC')"
    }
    column "is_deleted" {
      type = "Int8"
    }
    column "version" {
      type = "Int64"
    }
    engine "kafka" {
      collection = "msk_cluster"
      topic_list = "clickhouse_error_tracking_fingerprint_issue_state"
      group_name = "clickhouse-error-tracking-fingerprint-issue-state"
      format     = "JSONEachRow"
    }
  }
  materialized_view "error_tracking_fingerprint_issue_state_mv" {
    to_table = "posthog.writable_error_tracking_fingerprint_issue_state"
    query    = file("sql/error_tracking_fingerprint_issue_state_mv.sql")

    column "team_id" {
      type = "Int64"
    }
    column "fingerprint" {
      type = "String"
    }
    column "issue_id" {
      type = "UUID"
    }
    column "issue_name" {
      type = "Nullable(String)"
    }
    column "issue_description" {
      type = "Nullable(String)"
    }
    column "issue_status" {
      type = "String"
    }
    column "issue_severity" {
      type = "Nullable(String)"
    }
    column "assigned_user_id" {
      type = "Nullable(Int64)"
    }
    column "assigned_role_id" {
      type = "Nullable(UUID)"
    }
    column "first_seen" {
      type = "DateTime64(3, 'UTC')"
    }
    column "is_deleted" {
      type = "Int8"
    }
    column "version" {
      type = "Int64"
    }
    column "_timestamp" {
      type = "Nullable(DateTime)"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_partition" {
      type = "UInt64"
    }
  }

  # Local stacks create every topic with one partition, so only one consumer of this group can
  # get an assignment. The rest retry forever, which holds threads and floods the server log.
  patch_table "kafka_property_values" {
    engine "kafka" {
      collection          = "warpstream_ingestion"
      topic_list          = "clickhouse_property_values"
      group_name          = "clickhouse_property_values"
      format              = "JSONEachRow"
      num_consumers       = 1
      thread_per_consumer = true
    }
  }

}
