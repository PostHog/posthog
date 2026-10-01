# Kafka tables and the materialized views that consume them.


module "error_tracking_issue_fingerprint_embeddings_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(local.deployment.exclude, "error_tracking_issue_fingerprint_embeddings_mv")
  database = var.database
  name     = "error_tracking_issue_fingerprint_embeddings_mv"
  to_table = "${var.database}.writable_error_tracking_issue_fingerprint_embeddings"
  query    = <<-SQL
    SELECT
        team_id,
        model_name,
        embedding_version,
        fingerprint,
        _timestamp AS inserted_at,
        embeddings,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_error_tracking_issue_fingerprint_embeddings
  SQL
  override = try(local.deployment.overrides["error_tracking_issue_fingerprint_embeddings_mv"], {})

  depends_on = [
    module.kafka_error_tracking_issue_fingerprint_embeddings,
    module.writable_error_tracking_issue_fingerprint_embeddings,
  ]
}

module "error_tracking_issue_fingerprint_overrides_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(local.deployment.exclude, "error_tracking_issue_fingerprint_overrides_mv")
  database = var.database
  name     = "error_tracking_issue_fingerprint_overrides_mv"
  to_table = "${var.database}.writable_error_tracking_issue_fingerprint_overrides"
  query    = <<-SQL
    SELECT
        team_id,
        fingerprint,
        issue_id,
        is_deleted,
        version,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_error_tracking_issue_fingerprint_overrides
    WHERE version > 0
  SQL
  override = try(local.deployment.overrides["error_tracking_issue_fingerprint_overrides_mv"], {})

  depends_on = [
    module.kafka_error_tracking_issue_fingerprint_overrides,
    module.error_tracking_issue_fingerprint_overrides_family,
  ]
}


module "kafka_error_tracking_issue_fingerprint_embeddings" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(local.deployment.exclude, "kafka_error_tracking_issue_fingerprint_embeddings")
  database = var.database
  name     = "kafka_error_tracking_issue_fingerprint_embeddings"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_error_tracking_fingerprint_embeddings', kafka_topic_list = 'clickhouse_error_tracking_issue_fingerprint_embeddings'"
  columns  = local.kafka_error_tracking_issue_fingerprint_embeddings_columns
  override = try(local.deployment.overrides["kafka_error_tracking_issue_fingerprint_embeddings"], {})
}

module "kafka_error_tracking_issue_fingerprint_overrides" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(local.deployment.exclude, "kafka_error_tracking_issue_fingerprint_overrides")
  database = var.database
  name     = "kafka_error_tracking_issue_fingerprint_overrides"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse-error-tracking-issue-fingerprint-overrides', kafka_topic_list = 'clickhouse_error_tracking_issue_fingerprint'"
  columns  = local.kafka_error_tracking_issue_fingerprint_overrides_columns
  override = try(local.deployment.overrides["kafka_error_tracking_issue_fingerprint_overrides"], {})
}
