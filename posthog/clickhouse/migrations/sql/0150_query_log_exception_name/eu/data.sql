ALTER TABLE query_log_archive ADD COLUMN IF NOT EXISTS exception_name String ALIAS errorCodeToName(exception_code) AFTER exception_code
