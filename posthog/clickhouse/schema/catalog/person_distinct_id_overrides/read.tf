# Distributed tables, views and dictionaries that queries read from.

module "person_distinct_id_overrides_dict" {
  source = "../../lib/dictionary"

  enabled     = local.read && !contains(local.deployment.exclude, "person_distinct_id_overrides_dict")
  database    = var.database
  name        = "person_distinct_id_overrides_dict"
  primary_key = ["team_id", "distinct_id"]
  attributes = [
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "UUID" },
  ]
  source_clause = "CLICKHOUSE(USER '${var.dictionary_user}'${local.dictionary_password_clause} QUERY 'SELECT team_id, distinct_id, argMax(person_id, version) AS person_id FROM ${var.database}.person_distinct_id_overrides GROUP BY team_id, distinct_id')"
  layout        = "COMPLEX_KEY_HASHED()"
  lifetime      = "MIN 3600 MAX 18000"
  override      = try(local.deployment.overrides["person_distinct_id_overrides_dict"], {})

  depends_on = [
    module.person_distinct_id_overrides_family,
  ]
}
