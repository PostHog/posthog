# Distributed tables, views and dictionaries that queries read from.

module "channel_definition_dict" {
  source = "../../lib/dictionary"

  enabled     = local.read && !contains(local.deployment.exclude, "channel_definition_dict")
  database    = var.database
  name        = "channel_definition_dict"
  primary_key = ["domain", "kind"]
  attributes = [
    { name = "domain", type = "String" },
    { name = "kind", type = "String" },
    { name = "domain_type", type = "Nullable(String)" },
    { name = "type_if_paid", type = "Nullable(String)" },
    { name = "type_if_organic", type = "Nullable(String)" },
  ]
  source_clause = "CLICKHOUSE(USER '${var.dictionary_user}'${local.dictionary_password_clause} TABLE 'channel_definition')"
  layout        = "COMPLEX_KEY_HASHED()"
  lifetime      = "MIN 3000 MAX 3600"
  override      = try(local.deployment.overrides["channel_definition_dict"], {})

  depends_on = [
    module.channel_definition_family,
    clickhousedbops_table_contents.channel_definition,
  ]
}
