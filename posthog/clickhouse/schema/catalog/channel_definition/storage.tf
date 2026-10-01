# Tables that hold data, and the materialized views between them.


# channel_definitions.json is written by `python manage.py create_channel_definitions_file`. Each
# row has a sixth field that the table does not store. A root whose channel_definition is a
# Distributed table over another cluster excludes "channel_definition_contents".
resource "clickhousedbops_table_contents" "channel_definition" {
  count = local.storage && !contains(local.deployment.exclude, "channel_definition") && !contains(local.deployment.exclude, "channel_definition_contents") ? 1 : 0

  database = var.database
  table    = "channel_definition"
  format   = "JSONCompactEachRow"
  data     = join("\n", [for row in jsondecode(file("${path.module}/channel_definitions.json")) : jsonencode(slice(row, 0, 5))])

  depends_on = [module.channel_definition_family]
}
