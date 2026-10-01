# Distributed tables, views and dictionaries that queries read from.

# Every node holds its own copy of the bot definitions, which the dictionary reads locally.
# The table is small and its rows are declared below, so no node reads them from another cluster.

# web_bot_definitions.jsonl is generated from BOT_DEFINITIONS by `python manage.py write_bot_definitions_file`.
resource "clickhousedbops_table_contents" "web_bot_definition" {
  count = local.read && !contains(local.deployment.exclude, "web_bot_definition") && !contains(local.deployment.exclude, "web_bot_definition_contents") ? 1 : 0

  database = var.database
  table    = "web_bot_definition"
  format   = "JSONCompactEachRow"
  data     = file("${path.module}/web_bot_definitions.jsonl")

  depends_on = [module.web_bot_definition_family]
}

module "web_bot_definition_dict" {
  source = "../../lib/dictionary"

  enabled     = local.read && !contains(local.deployment.exclude, "web_bot_definition_dict")
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
  override      = try(local.deployment.overrides["web_bot_definition_dict"], {})

  depends_on = [
    module.web_bot_definition_family,
    clickhousedbops_table_contents.web_bot_definition,
  ]
}
