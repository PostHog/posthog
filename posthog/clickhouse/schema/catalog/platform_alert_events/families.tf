module "sharded_platform_alert_events_family" {
  source = "../../lib/table_family"

  name     = "platform_alert_events"
  database = var.database
  layout   = "global"
  columns  = local.sharded_platform_alert_events_columns
  storage = {
    partition_by = "toYYYYMM(occurred_at)"
    primary_key  = "(team_id, configuration_id, alert_id, occurred_at)"
    order_by     = "(team_id, configuration_id, alert_id, occurred_at, evaluation_key)"
    ttl          = var.ttl ? "expires_at" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    read = true
  }
  sharding_key = "cityHash64(team_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/noshard/${var.database}.platform_alert_events"
    cluster     = "aux"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_platform_alert_events", "platform_alert_events"], name) }
  })
  names = { storage = "sharded_platform_alert_events" }
}
