ALTER TABLE sharded_events DROP INDEX IF EXISTS properties_group_ai_large_keys_bf, DROP INDEX IF EXISTS properties_group_ai_large_values_bf, DROP COLUMN IF EXISTS properties_group_ai_large

ALTER TABLE events DROP COLUMN IF EXISTS properties_group_ai_large
