module "llma_metrics_daily_family" {
  source = "../../lib/table_family"

  name     = "llma_metrics_daily"
  database = var.database
  layout   = "global"
  columns = [
    { name = "date", type = "Date" },
    { name = "team_id", type = "UInt64" },
    { name = "metric_name", type = "String" },
    { name = "metric_value", type = "Float64" },
  ]
  storage = {
    partition_by = "toYYYYMM(date)"
    order_by     = "(team_id, date, metric_name)"
  }
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["llma_metrics_daily"], name) }
  })
}
