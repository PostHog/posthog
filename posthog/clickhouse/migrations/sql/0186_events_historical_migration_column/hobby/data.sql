ALTER TABLE sharded_events
ADD COLUMN IF NOT EXISTS historical_migration Bool

ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS minmax_historical_migration (historical_migration) TYPE minmax GRANULARITY 1

ALTER TABLE events
ADD COLUMN IF NOT EXISTS historical_migration Bool
