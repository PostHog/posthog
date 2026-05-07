ALTER TABLE sharded_raw_sessions_v3
DROP COLUMN IF EXISTS page_screen_autocapture_uniq_up_to,
ADD COLUMN IF NOT EXISTS page_screen_uniq_up_to AggregateFunction(uniqUpTo(1), Nullable(UUID)) AFTER screen_uniq,
ADD COLUMN IF NOT EXISTS has_autocapture SimpleAggregateFunction(max, Boolean) AFTER page_screen_uniq_up_to
;

ALTER TABLE writable_raw_sessions_v3
DROP COLUMN IF EXISTS page_screen_autocapture_uniq_up_to,
ADD COLUMN IF NOT EXISTS page_screen_uniq_up_to AggregateFunction(uniqUpTo(1), Nullable(UUID)) AFTER screen_uniq,
ADD COLUMN IF NOT EXISTS has_autocapture SimpleAggregateFunction(max, Boolean) AFTER page_screen_uniq_up_to
;

ALTER TABLE raw_sessions_v3
DROP COLUMN IF EXISTS page_screen_autocapture_uniq_up_to,
ADD COLUMN IF NOT EXISTS page_screen_uniq_up_to AggregateFunction(uniqUpTo(1), Nullable(UUID)) AFTER screen_uniq,
ADD COLUMN IF NOT EXISTS has_autocapture SimpleAggregateFunction(max, Boolean) AFTER page_screen_uniq_up_to
;
