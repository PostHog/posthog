# Column lists that more than one object uses.

locals {
  sharded_preaggregation_results_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "time_window_start", type = "DateTime64(6, 'UTC')" },
    { name = "expires_at", type = "DateTime64(6, 'UTC')", default_expression = "now() + toIntervalDay(7)" },
    { name = "breakdown_value", type = "Array(String)" },
    { name = "uniq_exact_state", type = "AggregateFunction(uniqExact, UUID)" },
  ]
}
