# Tables that hold data, and the materialized views between them.


module "posthog_document_embeddings_text_embedding_3_large_3072_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "posthog_document_embeddings_text_embedding_3_large_3072_mv")
  database = var.database
  name     = "posthog_document_embeddings_text_embedding_3_large_3072_mv"
  to_table = "${var.database}.writable_posthog_document_embeddings_text_embedding_3_large_3072"
  query    = <<-SQL
    SELECT
        team_id,
        product,
        document_type,
        rendering,
        document_id,
        timestamp,
        inserted_at,
        content,
        metadata,
        embedding,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.sharded_posthog_document_embeddings_buffer
    WHERE model_name = 'text-embedding-3-large-3072'
  SQL
  override = try(local.deployment.overrides["posthog_document_embeddings_text_embedding_3_large_3072_mv"], {})

  depends_on = [
    module.sharded_posthog_document_embeddings_buffer_family,
    module.sharded_posthog_document_embeddings_text_embedding_3_large_3072_family,
  ]
}

module "posthog_document_embeddings_text_embedding_3_small_1536_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "posthog_document_embeddings_text_embedding_3_small_1536_mv")
  database = var.database
  name     = "posthog_document_embeddings_text_embedding_3_small_1536_mv"
  to_table = "${var.database}.writable_posthog_document_embeddings_text_embedding_3_small_1536"
  query    = <<-SQL
    SELECT
        team_id,
        product,
        document_type,
        rendering,
        document_id,
        timestamp,
        inserted_at,
        content,
        metadata,
        embedding,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.sharded_posthog_document_embeddings_buffer
    WHERE model_name = 'text-embedding-3-small-1536'
  SQL
  override = try(local.deployment.overrides["posthog_document_embeddings_text_embedding_3_small_1536_mv"], {})

  depends_on = [
    module.sharded_posthog_document_embeddings_buffer_family,
    module.sharded_posthog_document_embeddings_text_embedding_3_small_1536_family,
  ]
}
