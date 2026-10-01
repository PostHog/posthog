# Column lists that more than one object uses.

locals {
  kafka_hog_invocation_results_columns = [
    { name = "team_id", type = "Int64" },
    { name = "function_kind", type = "LowCardinality(String)" },
    { name = "function_id", type = "String" },
    { name = "invocation_id", type = "String" },
    { name = "parent_run_id", type = "String" },
    { name = "status", type = "LowCardinality(String)" },
    { name = "attempts", type = "UInt8" },
    { name = "is_retry", type = "UInt8" },
    { name = "scheduled_at", type = "DateTime64(6, 'UTC')" },
    { name = "first_scheduled_at", type = "DateTime64(6, 'UTC')" },
    { name = "started_at", type = "Nullable(DateTime64(6, 'UTC'))" },
    { name = "finished_at", type = "Nullable(DateTime64(6, 'UTC'))" },
    { name = "duration_ms", type = "Nullable(UInt32)" },
    { name = "error_kind", type = "LowCardinality(String)" },
    { name = "error_message", type = "String" },
    { name = "event_uuid", type = "String" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "String" },
    { name = "invocation_globals", type = "String" },
    { name = "version", type = "UInt64" },
    { name = "is_deleted", type = "UInt8" },
  ]
}
