ALTER TABLE groups
DROP INDEX IF EXISTS is_deleted_idx

ALTER TABLE groups
DROP COLUMN IF EXISTS is_deleted

ALTER TABLE groups
ADD COLUMN IF NOT EXISTS is_deleted Boolean

ALTER TABLE groups
ADD INDEX IF NOT EXISTS is_deleted_idx (is_deleted) TYPE minmax GRANULARITY 1
