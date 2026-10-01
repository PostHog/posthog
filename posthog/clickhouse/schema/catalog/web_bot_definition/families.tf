# Its rows are declared below, so recreating the table loses nothing. web_bot_definition_dict
# reads it, and ClickHouse refuses to drop a table a dictionary reads unless the drop skips that check.
module "web_bot_definition_family" {
  source = "../../lib/table_family"

  name     = "web_bot_definition"
  database = var.database
  layout   = "global"
  columns  = local.web_bot_definition_columns
  # Its rows are declared below, so recreating the table loses nothing. web_bot_definition_dict
  # reads it, and ClickHouse refuses to drop a table a dictionary reads unless the drop skips that check.
  storage = {
    replicated = false
    order_by   = "id"
  }
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = contains(local.deployment.components, "read") ? ["storage"] : []
    overrides = {
      "web_bot_definition" = merge({ ignore_drop_dependencies = true, force_destroy = true }, try(local.deployment.overrides["web_bot_definition"], {}))
    }
  })
}
