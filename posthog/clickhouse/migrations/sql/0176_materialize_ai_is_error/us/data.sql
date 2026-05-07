ALTER TABLE sharded_events
ADD COLUMN IF NOT EXISTS `mat_$ai_is_error` Nullable(String)
MATERIALIZED JSONExtract(properties, '$ai_is_error', 'Nullable(String)')

ALTER TABLE events
ADD COLUMN IF NOT EXISTS `mat_$ai_is_error` Nullable(String)
COMMENT 'column_materializer::properties::$ai_is_error'

ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS `set_$ai_is_error` `mat_$ai_is_error`
TYPE set(7)
GRANULARITY 1
