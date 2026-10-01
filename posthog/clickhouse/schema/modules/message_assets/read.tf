# Distributed tables, views and dictionaries that queries read from.

module "message_assets" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "message_assets")
  database = var.database
  name     = "message_assets"
  engine   = "Distributed('aux', '${var.database}', 'message_assets_data')"
  columns = concat(local.kafka_message_assets_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ])
  override = try(var.overrides["message_assets"], {})
}
