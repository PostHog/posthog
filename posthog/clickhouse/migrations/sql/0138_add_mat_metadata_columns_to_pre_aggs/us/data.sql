ALTER TABLE web_pre_aggregated_stats
ADD COLUMN IF NOT EXISTS
mat_metadata_loggedIn Nullable(Bool),
ADD COLUMN IF NOT EXISTS
mat_metadata_backend Nullable(String)
AFTER has_fbclid

ALTER TABLE web_pre_aggregated_bounces
ADD COLUMN IF NOT EXISTS
mat_metadata_loggedIn Nullable(Bool),
ADD COLUMN IF NOT EXISTS
mat_metadata_backend Nullable(String)
AFTER has_fbclid

ALTER TABLE web_pre_aggregated_stats_staging
ADD COLUMN IF NOT EXISTS
mat_metadata_loggedIn Nullable(Bool),
ADD COLUMN IF NOT EXISTS
mat_metadata_backend Nullable(String)
AFTER has_fbclid

ALTER TABLE web_pre_aggregated_bounces_staging
ADD COLUMN IF NOT EXISTS
mat_metadata_loggedIn Nullable(Bool),
ADD COLUMN IF NOT EXISTS
mat_metadata_backend Nullable(String)
AFTER has_fbclid
