ALTER TABLE sharded_events
ADD COLUMN IF NOT EXISTS `mat_$ai_session_id` Nullable(String)
MATERIALIZED JSONExtract(properties, '$ai_session_id', 'Nullable(String)')

ALTER TABLE events
ADD COLUMN IF NOT EXISTS `mat_$ai_session_id` Nullable(String)
COMMENT 'column_materializer::properties::$ai_session_id'

ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS `bloom_filter_$ai_session_id` `mat_$ai_session_id`
TYPE bloom_filter
GRANULARITY 1

ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS `minmax_$ai_session_id` `mat_$ai_session_id`
TYPE minmax
GRANULARITY 1
