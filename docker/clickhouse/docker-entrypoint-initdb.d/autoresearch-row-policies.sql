-- Restrict the autoresearch user (see users-dev.xml) to its own queries in
-- system.query_log.
--
-- * SYSTEM FLUSH LOGS materializes system.query_log so the CREATE below
--   doesn't hit UNKNOWN_TABLE on first CH boot.
-- * initial_user (not user) is correct once distributed queries enter play.
-- * AS RESTRICTIVE ANDs with any later policy rather than widening access.
SYSTEM FLUSH LOGS;

CREATE ROW POLICY OR REPLACE autoresearch_own_queries_only ON system.query_log
    AS RESTRICTIVE
    FOR SELECT USING initial_user = currentUser()
    TO autoresearch;
