ALTER TABLE session_replay_embeddings on CLUSTER 'posthog'
        ADD COLUMN IF NOT EXISTS source_type LowCardinality(String)

ALTER TABLE writable_session_replay_embeddings on CLUSTER 'posthog'
        ADD COLUMN IF NOT EXISTS source_type LowCardinality(String)

ALTER TABLE sharded_session_replay_embeddings on CLUSTER 'posthog'
        ADD COLUMN IF NOT EXISTS source_type LowCardinality(String)
