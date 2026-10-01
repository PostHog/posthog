# Distributed tables that inserts go through.

module "writable_posthog_document_embeddings" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_posthog_document_embeddings")
  database = var.database
  name     = "writable_posthog_document_embeddings"
  engine   = "Distributed('posthog', '${var.database}', 'partitioned_sharded_posthog_document_embeddings', cityHash64(document_id))"
  columns  = local.sharded_posthog_document_embeddings_buffer_columns
  override = try(var.overrides["writable_posthog_document_embeddings"], {})
}

module "writable_posthog_document_embeddings_buffer" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_posthog_document_embeddings_buffer")
  database = var.database
  name     = "writable_posthog_document_embeddings_buffer"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_posthog_document_embeddings_buffer', cityHash64(document_id))"
  columns  = local.sharded_posthog_document_embeddings_buffer_columns
  override = try(var.overrides["writable_posthog_document_embeddings_buffer"], {})
}

module "writable_posthog_document_embeddings_text_embedding_3_large_3072" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_posthog_document_embeddings_text_embedding_3_large_3072")
  database = var.database
  name     = "writable_posthog_document_embeddings_text_embedding_3_large_3072"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_posthog_document_embeddings_text_embedding_3_large_3072', cityHash64(document_id))"
  columns  = local.sharded_posthog_document_embeddings_text_embedding_3_large_3072_columns
  override = try(var.overrides["writable_posthog_document_embeddings_text_embedding_3_large_3072"], {})
}

module "writable_posthog_document_embeddings_text_embedding_3_small_1536" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_posthog_document_embeddings_text_embedding_3_small_1536")
  database = var.database
  name     = "writable_posthog_document_embeddings_text_embedding_3_small_1536"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_posthog_document_embeddings_text_embedding_3_small_1536', cityHash64(document_id))"
  columns  = local.sharded_posthog_document_embeddings_text_embedding_3_large_3072_columns
  override = try(var.overrides["writable_posthog_document_embeddings_text_embedding_3_small_1536"], {})
}
