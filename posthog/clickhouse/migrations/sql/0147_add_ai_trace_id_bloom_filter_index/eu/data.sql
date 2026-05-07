ALTER TABLE sharded_events
ADD COLUMN IF NOT EXISTS `mat_$ai_trace_id` Nullable(String)
MATERIALIZED JSONExtract(properties, '$ai_trace_id', 'Nullable(String)')

ALTER TABLE events
ADD COLUMN IF NOT EXISTS `mat_$ai_trace_id` Nullable(String)
COMMENT 'column_materializer::properties::$ai_trace_id'

ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS `bloom_filter_$ai_trace_id` `mat_$ai_trace_id`
TYPE bloom_filter(0.001)
GRANULARITY 2
