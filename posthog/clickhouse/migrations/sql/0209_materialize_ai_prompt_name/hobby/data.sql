ALTER TABLE sharded_events
ADD COLUMN IF NOT EXISTS `mat_$ai_prompt_name` Nullable(String)
MATERIALIZED JSONExtract(properties, '$ai_prompt_name', 'Nullable(String)')

ALTER TABLE events
ADD COLUMN IF NOT EXISTS `mat_$ai_prompt_name` Nullable(String)
COMMENT 'column_materializer::properties::$ai_prompt_name'

ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS `bloom_filter_$ai_prompt_name` `mat_$ai_prompt_name`
TYPE bloom_filter
GRANULARITY 1

ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS `minmax_$ai_prompt_name` `mat_$ai_prompt_name`
TYPE minmax
GRANULARITY 1
