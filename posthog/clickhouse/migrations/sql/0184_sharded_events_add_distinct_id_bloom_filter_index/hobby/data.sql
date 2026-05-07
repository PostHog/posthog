ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS bloom_filter_distinct_id distinct_id
TYPE bloom_filter
GRANULARITY 1
