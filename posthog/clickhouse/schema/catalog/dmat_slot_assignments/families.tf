module "dmat_slot_assignments_family" {
  source = "../../lib/table_family"

  name     = "dmat_slot_assignments"
  database = var.database
  layout   = "global"
  columns = [
    { name = "team_id", type = "UInt64" },
    { name = "column_index", type = "UInt8" },
    { name = "property_name", type = "String" },
    { name = "version", type = "UInt32", default_expression = "toUnixTimestamp(now())" },
  ]
  storage = {
    engine      = "ReplacingMergeTree"
    replicated  = false
    engine_args = ["version"]
    order_by    = "(team_id, column_index)"
  }
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = contains(local.deployment.components, "test") ? ["storage"] : []
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["dmat_slot_assignments"], name) }
  })
}
