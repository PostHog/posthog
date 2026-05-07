ALTER TABLE sharded_events ON CLUSTER 'posthog' MODIFY COLUMN properties VARCHAR CODEC(ZSTD(3))
