# Kafka tables and the materialized views that consume them.

module "kafka_posthog_document_embeddings" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_posthog_document_embeddings")
  database = var.database
  name     = "kafka_posthog_document_embeddings"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_document_embeddings', kafka_topic_list = 'clickhouse_document_embeddings'"
  columns = [
    { name = "team_id", type = "Int64" },
    { name = "product", type = "LowCardinality(String)" },
    { name = "document_type", type = "LowCardinality(String)" },
    { name = "model_name", type = "LowCardinality(String)" },
    { name = "rendering", type = "LowCardinality(String)" },
    { name = "document_id", type = "String" },
    { name = "timestamp", type = "DateTime64(3, 'UTC')" },
    { name = "inserted_at", type = "DateTime64(3, 'UTC')" },
    { name = "content", type = "String" },
    { name = "metadata", type = "String" },
    { name = "embedding", type = "Array(Float64)" },
  ]
  override = try(var.overrides["kafka_posthog_document_embeddings"], {})
}

module "posthog_document_embeddings_kafka_to_buffer_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "posthog_document_embeddings_kafka_to_buffer_mv")
  database = var.database
  name     = "posthog_document_embeddings_kafka_to_buffer_mv"
  to_table = "${var.database}.writable_posthog_document_embeddings_buffer"
  query    = <<-SQL
    SELECT
        team_id,
        product,
        document_type,
        model_name,
        rendering,
        document_id,
        timestamp,
        _timestamp AS inserted_at,
        coalesce(content, '') AS content,
        coalesce(metadata, '{}') AS metadata,
        embedding,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_posthog_document_embeddings
  SQL
  override = try(var.overrides["posthog_document_embeddings_kafka_to_buffer_mv"], {})

  depends_on = [
    module.kafka_posthog_document_embeddings,
    module.writable_posthog_document_embeddings_buffer,
  ]
}
