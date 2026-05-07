ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS minmax_sharded_events_timestamp timestamp
TYPE minmax
GRANULARITY 1
