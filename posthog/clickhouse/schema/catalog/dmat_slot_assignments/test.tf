# Objects only the test suite uses, such as materialized views that stand in for the kafka pipeline.


module "dmat_slot_assignments_dict" {
  source = "../../lib/dictionary"

  enabled     = local.test && !contains(local.deployment.exclude, "dmat_slot_assignments_dict")
  database    = var.database
  name        = "dmat_slot_assignments_dict"
  primary_key = ["team_id", "column_index"]
  attributes = [
    { name = "team_id", type = "UInt64" },
    { name = "column_index", type = "UInt8" },
    { name = "property_name", type = "String" },
  ]
  source_clause = "CLICKHOUSE(QUERY 'SELECT     team_id,     column_index,     property_name FROM     `${var.database}`.`dmat_slot_assignments` FINAL' USER '${var.dictionary_user}'${local.dictionary_password_clause})"
  layout        = "COMPLEX_KEY_HASHED()"
  lifetime      = "MIN 600 MAX 1200"
  override      = try(local.deployment.overrides["dmat_slot_assignments_dict"], {})

  depends_on = [
    module.dmat_slot_assignments_family,
  ]
}
