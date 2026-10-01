# Column lists that more than one object uses.

locals {
  kafka_error_tracking_issue_fingerprint_overrides_columns = [
    { name = "team_id", type = "Int64" },
    { name = "fingerprint", type = "String" },
    { name = "issue_id", type = "UUID" },
    { name = "is_deleted", type = "Int8" },
    { name = "version", type = "Int64" },
  ]

  kafka_error_tracking_issue_fingerprint_embeddings_columns = [
    { name = "team_id", type = "Int64" },
    { name = "model_name", type = "LowCardinality(String)" },
    { name = "embedding_version", type = "Int64" },
    { name = "fingerprint", type = "String" },
    { name = "inserted_at", type = "DateTime64(3, 'UTC')" },
    { name = "embeddings", type = "Array(Float64)" },
  ]

  error_tracking_issue_fingerprint_overrides_columns = concat(local.kafka_error_tracking_issue_fingerprint_overrides_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ])

  kafka_error_tracking_fingerprint_issue_state_columns = [
    { name = "team_id", type = "Int64" },
    { name = "fingerprint", type = "String" },
    { name = "issue_id", type = "UUID" },
    { name = "issue_name", type = "Nullable(String)" },
    { name = "issue_description", type = "Nullable(String)" },
    { name = "issue_status", type = "String" },
    { name = "issue_severity", type = "Nullable(String)" },
    { name = "assigned_user_id", type = "Nullable(Int64)" },
    { name = "assigned_role_id", type = "Nullable(UUID)" },
    { name = "first_seen", type = "DateTime64(3, 'UTC')" },
    { name = "is_deleted", type = "Int8" },
    { name = "version", type = "Int64" },
  ]

  raw_error_tracking_fingerprint_issue_state_columns = concat(local.kafka_error_tracking_fingerprint_issue_state_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ])
}
