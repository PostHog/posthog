# Distributed tables that inserts go through.


module "writable_error_tracking_issue_fingerprint_embeddings" {
  source = "../../lib/table"

  enabled  = local.write && !contains(local.deployment.exclude, "writable_error_tracking_issue_fingerprint_embeddings")
  database = var.database
  name     = "writable_error_tracking_issue_fingerprint_embeddings"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'error_tracking_issue_fingerprint_embeddings')"
  columns = concat(local.kafka_error_tracking_issue_fingerprint_embeddings_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ])
  override = try(local.deployment.overrides["writable_error_tracking_issue_fingerprint_embeddings"], {})
}
