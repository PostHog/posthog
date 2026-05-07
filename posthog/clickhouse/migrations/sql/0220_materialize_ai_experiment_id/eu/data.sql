ALTER TABLE sharded_events
ADD COLUMN IF NOT EXISTS `mat_$ai_experiment_id` Nullable(String)
DEFAULT JSONExtract(properties, '$ai_experiment_id', 'Nullable(String)')

ALTER TABLE events
ADD COLUMN IF NOT EXISTS `mat_$ai_experiment_id` Nullable(String)
COMMENT 'column_materializer::properties::$ai_experiment_id'

ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS `bloom_filter_$ai_experiment_id` `mat_$ai_experiment_id`
TYPE bloom_filter
GRANULARITY 1

ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS `minmax_$ai_experiment_id` `mat_$ai_experiment_id`
TYPE minmax
GRANULARITY 1
