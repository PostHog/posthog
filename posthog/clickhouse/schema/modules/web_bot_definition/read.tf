# Distributed tables, views and dictionaries that queries read from.

# Every node holds its own copy of the bot definitions, which the dictionary reads locally.
# The table is small and its rows are declared below, so no node reads them from another cluster.
module "web_bot_definition" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "web_bot_definition")
  database = var.database
  name     = "web_bot_definition"
  engine   = "MergeTree"
  order_by = "id"
  columns  = local.web_bot_definition_columns
  # Its rows are declared below, so recreating the table loses nothing. web_bot_definition_dict
  # reads it, and ClickHouse refuses to drop a table a dictionary reads unless the drop skips that check.
  override = merge({ ignore_drop_dependencies = true, force_destroy = true }, try(var.overrides["web_bot_definition"], {}))
}

# web_bot_definitions.jsonl is generated from BOT_DEFINITIONS by `python manage.py write_bot_definitions_file`.
resource "clickhousedbops_table_contents" "web_bot_definition" {
  count = local.read && !contains(var.exclude, "web_bot_definition") && !contains(var.exclude, "web_bot_definition_contents") ? 1 : 0

  database = var.database
  table    = "web_bot_definition"
  format   = "JSONCompactEachRow"
  data     = file("${path.module}/web_bot_definitions.jsonl")

  depends_on = [module.web_bot_definition]
}

module "web_bot_definition_dict" {
  source = "../../lib/dictionary"

  enabled     = local.read && !contains(var.exclude, "web_bot_definition_dict")
  database    = var.database
  name        = "web_bot_definition_dict"
  primary_key = ["regexp"]
  attributes = [
    { name = "regexp", type = "String" },
    { name = "name", type = "String" },
    { name = "category", type = "String" },
    { name = "traffic_type", type = "String" },
    { name = "operator", type = "String" },
  ]
  source_clause = "CLICKHOUSE(USER '${var.dictionary_user}'${local.dictionary_password_clause} DB '${var.database}' TABLE 'web_bot_definition')"
  layout        = "REGEXP_TREE()"
  lifetime      = "MIN 3000 MAX 3600"
  override      = try(var.overrides["web_bot_definition_dict"], {})

  depends_on = [
    module.web_bot_definition,
    clickhousedbops_table_contents.web_bot_definition,
  ]
}
