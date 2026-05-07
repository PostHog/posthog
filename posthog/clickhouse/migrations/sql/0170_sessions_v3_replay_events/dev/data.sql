ALTER TABLE sharded_raw_sessions_v3
DROP COLUMN IF EXISTS person_id

ALTER TABLE writable_raw_sessions_v3
DROP COLUMN IF EXISTS person_id

ALTER TABLE raw_sessions_v3
DROP COLUMN IF EXISTS person_id

ALTER TABLE sharded_raw_sessions_v3
ADD COLUMN IF NOT EXISTS has_replay_events SimpleAggregateFunction(max, Boolean) AFTER flag_values;

ALTER TABLE writable_raw_sessions_v3
ADD COLUMN IF NOT EXISTS has_replay_events SimpleAggregateFunction(max, Boolean) AFTER flag_values;

ALTER TABLE raw_sessions_v3
ADD COLUMN IF NOT EXISTS has_replay_events SimpleAggregateFunction(max, Boolean) AFTER flag_values;
