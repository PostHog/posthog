module "adhoc_events_deletion_family" {
  source = "../../lib/table_family"

  name     = "adhoc_events_deletion"
  database = var.database
  layout   = "global"
  columns = [
    { name = "team_id", type = "Int64" },
    { name = "uuid", type = "UUID" },
    { name = "data_deletion_request_id", type = "Nullable(UUID)" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()" },
    { name = "deleted_at", type = "DateTime" },
    { name = "is_deleted", type = "UInt8", default_expression = "0" },
  ]
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["deleted_at", "is_deleted"]
    order_by    = "(team_id, uuid)"
    ttl         = var.ttl ? "deleted_at + toIntervalMonth(3) WHERE is_deleted = 1" : null
  }
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["adhoc_events_deletion"], name) }
  })
}
