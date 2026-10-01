# Distributed tables, views and dictionaries that queries read from.

module "error_tracking_fingerprint_issue_state" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "error_tracking_fingerprint_issue_state")
  database = var.database
  name     = "error_tracking_fingerprint_issue_state"
  engine   = "Distributed('aux', '${var.database}', 'raw_error_tracking_fingerprint_issue_state')"
  columns  = local.raw_error_tracking_fingerprint_issue_state_columns
  override = try(var.overrides["error_tracking_fingerprint_issue_state"], {})
}
