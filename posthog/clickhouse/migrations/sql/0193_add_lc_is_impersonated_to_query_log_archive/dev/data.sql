ALTER TABLE query_log_archive ADD COLUMN IF NOT EXISTS lc_is_impersonated Bool AFTER lc_user_id
