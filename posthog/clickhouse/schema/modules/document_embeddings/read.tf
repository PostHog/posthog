# Distributed tables, views and dictionaries that queries read from.

module "distributed_posthog_document_embeddings" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "distributed_posthog_document_embeddings")
  database = var.database
  name     = "distributed_posthog_document_embeddings"
  engine   = "Distributed('posthog', '${var.database}', 'partitioned_sharded_posthog_document_embeddings', cityHash64(document_id))"
  columns  = local.sharded_posthog_document_embeddings_buffer_columns
  override = try(var.overrides["distributed_posthog_document_embeddings"], {})
}

module "distributed_posthog_document_embeddings_text_embedding_3_large_3072" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "distributed_posthog_document_embeddings_text_embedding_3_large_3072")
  database = var.database
  name     = "distributed_posthog_document_embeddings_text_embedding_3_large_3072"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_posthog_document_embeddings_text_embedding_3_large_3072', cityHash64(document_id))"
  columns  = local.sharded_posthog_document_embeddings_text_embedding_3_large_3072_columns
  override = try(var.overrides["distributed_posthog_document_embeddings_text_embedding_3_large_3072"], {})
}

module "distributed_posthog_document_embeddings_text_embedding_3_small_1536" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "distributed_posthog_document_embeddings_text_embedding_3_small_1536")
  database = var.database
  name     = "distributed_posthog_document_embeddings_text_embedding_3_small_1536"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_posthog_document_embeddings_text_embedding_3_small_1536', cityHash64(document_id))"
  columns  = local.sharded_posthog_document_embeddings_text_embedding_3_large_3072_columns
  override = try(var.overrides["distributed_posthog_document_embeddings_text_embedding_3_small_1536"], {})
}

module "posthog_document_embeddings_union_view" {
  source = "../../lib/view"

  enabled  = local.read && !contains(var.exclude, "posthog_document_embeddings_union_view")
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
  override = try(var.overrides["posthog_document_embeddings_union_view"], {})

  depends_on = [
    module.distributed_posthog_document_embeddings_text_embedding_3_large_3072,
    module.distributed_posthog_document_embeddings_text_embedding_3_small_1536,
  ]
}
