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
--
-- `AS RESTRICTIVE` so that any additional row policy later attached to this
-- table (e.g. a broader admin one targeting `ALL`) is AND'd with ours rather
-- than OR'd — permissive policies additively widen access, which is the
-- opposite of what we want here.
--
-- The other sensitive system tables (processes, text_log, trace_log,
-- part_log, metric_log, query_thread_log, errors, stack_trace,
-- opentelemetry_span_log, session_log, parts, mutations, etc.) are already
-- access-denied by default in ClickHouse 26.3+ without an explicit grant —
-- the autoresearch user has no grants on them, so SELECTs return code 497
-- ACCESS_DENIED. `system.tables` / `columns` / `databases` / `settings` /
-- `functions` / `one` remain readable as schema-introspection essentials;
-- the first three are auto-filtered by the user's grants so the agent sees
-- only tables it's actually allowed to SELECT from.
CREATE ROW POLICY OR REPLACE autoresearch_own_queries_only ON system.query_log
    AS RESTRICTIVE
    FOR SELECT USING initial_user = currentUser()
    TO autoresearch;
