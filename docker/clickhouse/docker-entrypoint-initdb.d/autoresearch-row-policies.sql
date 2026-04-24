-- Restrict the `autoresearch` CH user (see users-dev.xml) to only see its own
-- rows in system.query_log. Without this, a cross-user grant would let the
-- autoresearch-driven LLM read queries from every user on the dev CH server,
-- leaking unrelated query text + parameters.
--
-- `initial_user = currentUser()` matches on the user who submitted the query;
-- for our single-node setup that's the same as `user`, but `initial_user` is
-- the correct choice once distributed queries enter the picture (distributed
-- sub-queries run as the internal distributed user, but `initial_user` stays
-- set to the original caller).
CREATE ROW POLICY OR REPLACE autoresearch_own_queries_only ON system.query_log
    FOR SELECT USING initial_user = currentUser()
    TO autoresearch;
