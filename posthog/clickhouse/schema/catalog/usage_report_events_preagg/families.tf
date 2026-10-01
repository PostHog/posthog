module "sharded_usage_report_events_preagg_family" {
  source = "../../lib/table_family"

  name     = "usage_report_events_preagg"
  database = var.database
  columns  = local.sharded_usage_report_events_preagg_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "date"
    order_by     = "(date, team_id, person_mode, lib, event)"
    ttl          = var.ttl ? "date + toIntervalDay(14)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  sharding_key = "sipHash64(date)"
  deployment = merge({
    cluster = "aux"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_usage_report_events_preagg", "usage_report_events_preagg", "writable_usage_report_events_preagg"], name) }
  })
}
