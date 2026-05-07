ALTER TABLE sharded_events ON CLUSTER posthog
ADD INDEX IF NOT EXISTS `minmax_inserted_at` COALESCE(`inserted_at`, `_timestamp`)
TYPE minmax
GRANULARITY 1

ALTER TABLE sharded_events ON CLUSTER posthog
MATERIALIZE INDEX `minmax_inserted_at`
