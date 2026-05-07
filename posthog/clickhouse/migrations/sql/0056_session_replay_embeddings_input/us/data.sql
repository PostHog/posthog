ALTER TABLE session_replay_embeddings on CLUSTER 'posthog'
        ADD COLUMN IF NOT EXISTS input String

ALTER TABLE writable_session_replay_embeddings on CLUSTER 'posthog'
        ADD COLUMN IF NOT EXISTS input String

ALTER TABLE sharded_session_replay_embeddings on CLUSTER 'posthog'
        ADD COLUMN IF NOT EXISTS input String
