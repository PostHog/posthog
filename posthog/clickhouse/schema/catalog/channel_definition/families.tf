# Every node holds its own copy, whose rows are declared below, so recreating the table loses
# nothing. channel_definition_dict reads it, and ClickHouse refuses to drop a table a dictionary
# reads unless the drop skips that check.
module "channel_definition_family" {
  source = "../../lib/table_family"

  name     = "channel_definition"
  database = var.database
  layout   = "global"
  columns = [
    { name = "domain", type = "String" },
    { name = "kind", type = "String" },
    { name = "domain_type", type = "Nullable(String)" },
    { name = "type_if_paid", type = "Nullable(String)" },
    { name = "type_if_organic", type = "Nullable(String)" },
  ]
  # Every node holds its own copy, whose rows are declared below, so recreating the table loses
  # nothing. channel_definition_dict reads it, and ClickHouse refuses to drop a table a dictionary
  # reads unless the drop skips that check.
  storage = {
    replicated = false
    order_by   = "(domain, kind)"
  }
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides = {
      "channel_definition" = merge({ ignore_drop_dependencies = true, force_destroy = true }, try(local.deployment.overrides["channel_definition"], {}))
    }
  })
}
