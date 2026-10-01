# Distributed tables, views and dictionaries that queries read from.




module "posthog_document_embeddings_union_view" {
  source = "../../lib/view"

  enabled  = local.read && !contains(local.deployment.exclude, "posthog_document_embeddings_union_view")
  database = var.database
  name     = "posthog_document_embeddings_union_view"
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
        _partition,
        'text-embedding-3-small-1536' AS model_name
    FROM ${var.database}.distributed_posthog_document_embeddings_text_embedding_3_small_1536
    UNION ALL
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
        _partition,
        'text-embedding-3-large-3072' AS model_name
    FROM ${var.database}.distributed_posthog_document_embeddings_text_embedding_3_large_3072
  SQL
  override = try(local.deployment.overrides["posthog_document_embeddings_union_view"], {})

  depends_on = [
    module.sharded_posthog_document_embeddings_text_embedding_3_large_3072_family,
    module.sharded_posthog_document_embeddings_text_embedding_3_small_1536_family,
  ]
}
