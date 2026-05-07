ALTER TABLE sharded_preaggregation_results
ADD COLUMN IF NOT EXISTS expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY AFTER time_window_start

ALTER TABLE sharded_preaggregation_results
MODIFY TTL expires_at

ALTER TABLE preaggregation_results
ADD COLUMN IF NOT EXISTS expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY AFTER time_window_start
