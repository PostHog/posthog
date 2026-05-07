ALTER TABLE sharded_raw_sessions_v3
ADD COLUMN IF NOT EXISTS event_names SimpleAggregateFunction(groupUniqArrayArray, Array(String)) AFTER flag_values

ALTER TABLE writable_raw_sessions_v3
ADD COLUMN IF NOT EXISTS event_names SimpleAggregateFunction(groupUniqArrayArray, Array(String)) AFTER flag_values

ALTER TABLE raw_sessions_v3
ADD COLUMN IF NOT EXISTS event_names SimpleAggregateFunction(groupUniqArrayArray, Array(String)) AFTER flag_values

ALTER TABLE sharded_raw_sessions_v3
ADD INDEX IF NOT EXISTS event_names_bloom_filter event_names TYPE bloom_filter() GRANULARITY 1

ALTER TABLE sharded_raw_sessions_v3
ADD COLUMN IF NOT EXISTS flag_keys SimpleAggregateFunction(groupUniqArrayArray, Array(String)) AFTER flag_values

ALTER TABLE writable_raw_sessions_v3
ADD COLUMN IF NOT EXISTS flag_keys SimpleAggregateFunction(groupUniqArrayArray, Array(String)) AFTER flag_values

ALTER TABLE raw_sessions_v3
ADD COLUMN IF NOT EXISTS flag_keys SimpleAggregateFunction(groupUniqArrayArray, Array(String)) AFTER flag_values

ALTER TABLE sharded_raw_sessions_v3
ADD INDEX IF NOT EXISTS flag_keys_bloom_filter flag_keys TYPE bloom_filter() GRANULARITY 1

ALTER TABLE sharded_raw_sessions_v3
DROP COLUMN IF EXISTS urls

ALTER TABLE sharded_raw_sessions_v3
ADD COLUMN IF NOT EXISTS urls SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String)) AFTER max_inserted_at

ALTER TABLE writable_raw_sessions_v3
DROP COLUMN IF EXISTS urls

ALTER TABLE writable_raw_sessions_v3
ADD COLUMN IF NOT EXISTS urls SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String)) AFTER max_inserted_at

ALTER TABLE raw_sessions_v3
DROP COLUMN IF EXISTS urls

ALTER TABLE raw_sessions_v3
ADD COLUMN IF NOT EXISTS urls SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String)) AFTER max_inserted_at
