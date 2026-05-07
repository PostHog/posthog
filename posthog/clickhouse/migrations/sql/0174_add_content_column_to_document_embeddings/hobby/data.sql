ALTER TABLE partitioned_sharded_posthog_document_embeddings
ADD COLUMN IF NOT EXISTS content String DEFAULT ''
