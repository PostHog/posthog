# Tables that hold data, and the materialized views between them.

module "channel_definition" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "channel_definition")
  database = var.database
  name     = "channel_definition"
  engine   = "MergeTree"
  order_by = "(domain, kind)"
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
  override = merge({ ignore_drop_dependencies = true, force_destroy = true }, try(var.overrides["channel_definition"], {}))
}

# channel_definitions.json is written by `python manage.py create_channel_definitions_file`. Each
# row has a sixth field that the table does not store. A root whose channel_definition is a
# Distributed table over another cluster excludes "channel_definition_contents".
resource "clickhousedbops_table_contents" "channel_definition" {
  count = local.storage && !contains(var.exclude, "channel_definition") && !contains(var.exclude, "channel_definition_contents") ? 1 : 0

  database = var.database
  table    = "channel_definition"
  format   = "JSONCompactEachRow"
  data     = join("\n", [for row in jsondecode(file("${path.module}/channel_definitions.json")) : jsonencode(slice(row, 0, 5))])

  depends_on = [module.channel_definition]
}
