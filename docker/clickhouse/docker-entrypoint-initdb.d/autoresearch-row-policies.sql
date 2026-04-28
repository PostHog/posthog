-- Restrict the autoresearch user (see users-dev.xml) to its own queries in
-- the system profiling tables.
--
-- * SYSTEM FLUSH LOGS materializes the tables so the CREATE statements below
--   don't hit UNKNOWN_TABLE on first CH boot.
-- * `initial_user` (not `user`) is correct once distributed queries enter play.
-- * `AS RESTRICTIVE` ANDs with any later policy rather than widening access.
-- * `system.text_log` and `system.trace_log` have no user column; filter by
--   `query_id` membership in the autoresearch-owned subset of `system.query_log`.
--   CH evaluates the IN-subquery once per outer query (Set-style), so the
--   per-row cost is constant; ad-hoc lookups are fine.
SYSTEM FLUSH LOGS;

CREATE ROW POLICY OR REPLACE autoresearch_own_queries_only ON system.query_log
    AS RESTRICTIVE
    FOR SELECT USING initial_user = currentUser()
    TO autoresearch;

CREATE ROW POLICY OR REPLACE autoresearch_own_query_threads_only ON system.query_thread_log
    AS RESTRICTIVE
    FOR SELECT USING initial_user = currentUser()
    TO autoresearch;

CREATE ROW POLICY OR REPLACE autoresearch_own_text_log_only ON system.text_log
    AS RESTRICTIVE
    FOR SELECT USING query_id IN (
        SELECT query_id FROM system.query_log WHERE initial_user = currentUser()
    )
    TO autoresearch;

CREATE ROW POLICY OR REPLACE autoresearch_own_trace_log_only ON system.trace_log
    AS RESTRICTIVE
    FOR SELECT USING query_id IN (
        SELECT query_id FROM system.query_log WHERE initial_user = currentUser()
    )
    TO autoresearch;
