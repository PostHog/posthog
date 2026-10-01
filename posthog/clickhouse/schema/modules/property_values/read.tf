# Distributed tables, views and dictionaries that queries read from.

module "property_values_distributed" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "property_values_distributed")
  database = var.database
  name     = "property_values_distributed"
  engine   = "Distributed('aux', '${var.database}', 'property_values')"
  columns  = local.property_values_columns
  override = try(var.overrides["property_values_distributed"], {})
}
