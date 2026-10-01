# Column lists that more than one object uses.

locals {
  sharded_experiment_metric_events_preaggregated_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "entity_id", type = "String" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "event_uuid", type = "UUID" },
    { name = "session_id", type = "String" },
    { name = "numeric_value", type = "Float64", default_expression = "0" },
    { name = "steps", type = "Array(UInt8)", default_expression = "[]" },
    { name = "computed_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "expires_at", type = "Date", default_expression = "today() + toIntervalDay(7)" },
  ]

  sharded_experiment_exposures_preaggregated_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "entity_id", type = "String" },
    { name = "variant", type = "String" },
    { name = "first_exposure_time", type = "DateTime64(6, 'UTC')" },
    { name = "last_exposure_time", type = "DateTime64(6, 'UTC')" },
    { name = "exposure_event_uuid", type = "UUID" },
    { name = "exposure_session_id", type = "String" },
    { name = "breakdown_value", type = "Array(String)" },
    { name = "computed_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "expires_at", type = "Date", default_expression = "today() + toIntervalDay(7)" },
  ]
}
