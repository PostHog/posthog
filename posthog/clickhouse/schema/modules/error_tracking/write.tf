# Distributed tables that inserts go through.

module "writable_error_tracking_fingerprint_issue_state" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_error_tracking_fingerprint_issue_state")
  database = var.database
  name     = "writable_error_tracking_fingerprint_issue_state"
  engine   = "Distributed('aux', '${var.database}', 'raw_error_tracking_fingerprint_issue_state')"
  columns  = local.raw_error_tracking_fingerprint_issue_state_columns
  override = try(var.overrides["writable_error_tracking_fingerprint_issue_state"], {})
}

module "writable_error_tracking_issue_fingerprint_embeddings" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_error_tracking_issue_fingerprint_embeddings")
  database = var.database
  name     = "writable_error_tracking_issue_fingerprint_embeddings"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'error_tracking_issue_fingerprint_embeddings')"
  columns = concat(local.kafka_error_tracking_issue_fingerprint_embeddings_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ])
  override = try(var.overrides["writable_error_tracking_issue_fingerprint_embeddings"], {})
}

module "writable_error_tracking_issue_fingerprint_overrides" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_error_tracking_issue_fingerprint_overrides")
  database = var.database
  name     = "writable_error_tracking_issue_fingerprint_overrides"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'error_tracking_issue_fingerprint_overrides')"
  columns  = local.error_tracking_issue_fingerprint_overrides_columns
  override = try(var.overrides["writable_error_tracking_issue_fingerprint_overrides"], {})
}
