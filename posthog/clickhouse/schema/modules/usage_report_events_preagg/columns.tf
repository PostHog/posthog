# Column lists that more than one object uses.

locals {
  sharded_usage_report_events_preagg_columns = [
    { name = "date", type = "Date" },
    { name = "team_id", type = "Int64" },
    { name = "person_mode", type = "LowCardinality(String)" },
    { name = "lib", type = "LowCardinality(String)" },
    { name = "event", type = "String" },
    { name = "distinct_events_unique", type = "AggregateFunction(uniqExact, Tuple(UInt64, UInt64, UInt64))" },
    { name = "event_count", type = "AggregateFunction(sum, UInt64)" },
  ]
}
