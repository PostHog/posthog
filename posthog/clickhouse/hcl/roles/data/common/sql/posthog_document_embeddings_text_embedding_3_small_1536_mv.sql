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
FROM posthog.sharded_posthog_document_embeddings_buffer
WHERE model_name = 'text-embedding-3-small-1536'
