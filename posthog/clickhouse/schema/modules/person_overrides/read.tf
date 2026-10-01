# Distributed tables, views and dictionaries that queries read from.

module "person_overrides_dict" {
  source = "../../lib/dictionary"

  enabled     = local.read && !contains(var.exclude, "person_overrides_dict")
  database    = var.database
  name        = "person_overrides_dict"
  primary_key = ["team_id", "old_person_id"]
  attributes = [
    { name = "team_id", type = "INT" },
    { name = "old_person_id", type = "UUID" },
    { name = "override_person_id", type = "UUID" },
  ]
  source_clause = "CLICKHOUSE(USER '${var.dictionary_user}'${local.dictionary_password_clause} QUERY '\\nSELECT\\n    team_id,\\n    old_person_id,\\n    argMax(override_person_id, version)\\nFROM\\n    `${var.database}`.`person_overrides` AS overrides\\nGROUP BY\\n    team_id,\\n    old_person_id\\n')"
  layout        = "COMPLEX_KEY_HASHED(PREALLOCATE 1)"
  lifetime      = "MIN 5 MAX 10"
  override      = try(var.overrides["person_overrides_dict"], {})

  depends_on = [
    module.person_overrides,
  ]
}
