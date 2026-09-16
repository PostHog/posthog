database "posthog" {
  table "writable_error_tracking_fingerprint_issue_state" {
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
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_partition" {
      type = "UInt64"
    }
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "raw_error_tracking_fingerprint_issue_state"
    }
  }
}
