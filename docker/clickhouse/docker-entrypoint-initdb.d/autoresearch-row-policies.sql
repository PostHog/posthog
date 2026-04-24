-- Restrict the `autoresearch` user (see users-dev.xml) to its own rows in
-- system.query_log. Without this, its SELECT grant would expose every other
-- user's query text + parameters on the shared dev CH server.
--
-- * `SYSTEM FLUSH LOGS` materializes system.query_log on a fresh data dir so
--   the CREATE ROW POLICY below doesn't fail with UNKNOWN_TABLE during CH
--   first-boot init (system log tables are created lazily on first flush).
-- * `initial_user = currentUser()` matches the submitting user; `initial_user`
--   (not `user`) is correct once distributed queries are in play.
-- * `AS RESTRICTIVE` so a later permissive policy on the same table AND's
--   with this one rather than widening access.
SYSTEM FLUSH LOGS;

CREATE ROW POLICY OR REPLACE autoresearch_own_queries_only ON system.query_log
    AS RESTRICTIVE
    FOR SELECT USING initial_user = currentUser()
    TO autoresearch;
