"""All SQL for the posthog_eventproperty cleanup job, in one place.

Plans were verified on the production replicas. Each DELETE re-checks its own predicate so a
row that became legitimate between discovery and deletion is never removed.
"""

TABLE = "posthog_eventproperty"
REQUIRED_INDEXES = (
    "posthog_event_property_unique_proj_event_property",
    "posthog_eventproperty_team_id_and_property_r32khd9s",
)

PREFLIGHT_PRIMARY = "SELECT pg_is_in_recovery(), current_database()"
PREFLIGHT_INDEXES = "SELECT indexname FROM pg_indexes WHERE tablename = %(table)s"
PREFLIGHT_REPLICATION_SLOTS = "SELECT slot_name, active FROM pg_replication_slots"

TEAM_ORG_STATE = """
SELECT t.id AS team_id,
       t.project_id,
       o.has_active_subscription
FROM posthog_team t
JOIN posthog_project p ON p.id = t.project_id
JOIN posthog_organization o ON o.id = p.organization_id
WHERE t.id = ANY(%(team_ids)s)
ORDER BY o.has_active_subscription NULLS FIRST, t.id
"""

# Mode 2a. Teams that own at least one non-event property definition. Index-only on
# posthog_pro_team_id_eac36d_idx (team_id, type, is_numerical).
POLLUTION_TEAM_UNIVERSE = "SELECT DISTINCT team_id FROM posthog_propertydefinition WHERE type <> 1"

# Mode 2a. Property names that exist only as non-event definitions in the project. Nested Loop
# Anti Join on posthog_pro_project_3583d2_idx and posthog_propdef_proj_uniq.
POLLUTION_CANDIDATE_NAMES = """
SELECT DISTINCT pd.name
FROM posthog_propertydefinition pd
WHERE coalesce(pd.project_id, pd.team_id) = %(project_id)s
  AND pd.type <> 1
  AND NOT EXISTS (
      SELECT 1 FROM posthog_propertydefinition e
      WHERE coalesce(e.project_id, e.team_id) = %(project_id)s
        AND e.name = pd.name
        AND e.type = 1)
ORDER BY pd.name
"""

POLLUTION_ESTIMATE = """
EXPLAIN (FORMAT JSON)
SELECT 1 FROM posthog_eventproperty WHERE team_id = %(team_id)s AND property = %(property)s
"""

POLLUTION_DELETE = """
DELETE FROM posthog_eventproperty
WHERE ctid = ANY(ARRAY(
        SELECT ctid FROM posthog_eventproperty
        WHERE team_id = %(team_id)s AND property = %(property)s
        LIMIT %(batch)s))
  AND coalesce(project_id, team_id) = %(project_id)s
  AND NOT EXISTS (
      SELECT 1 FROM posthog_propertydefinition e
      WHERE coalesce(e.project_id, e.team_id) = %(project_id)s
        AND e.name = %(property)s
        AND e.type = 1)
"""

# Mode 2b. Teams that own at least one stale event definition. One scan of posthog_eventdefinition
# instead of one query per team.
RETENTION_TEAM_UNIVERSE = """
SELECT DISTINCT team_id
FROM posthog_eventdefinition
WHERE last_seen_at IS NOT NULL AND last_seen_at < now() - make_interval(days => %(days)s)
"""

# Mode 2b. Event names not seen for N days. NULL last_seen_at is unknown and never eligible.
RETENTION_CANDIDATE_EVENTS = """
SELECT name
FROM posthog_eventdefinition
WHERE coalesce(project_id, team_id) = %(project_id)s
  AND last_seen_at IS NOT NULL
  AND last_seen_at < now() - make_interval(days => %(days)s)
ORDER BY name
"""

RETENTION_ESTIMATE = """
EXPLAIN (FORMAT JSON)
SELECT 1 FROM posthog_eventproperty
WHERE coalesce(project_id, team_id) = %(project_id)s AND event = ANY(%(names)s)
"""

RETENTION_DELETE = """
DELETE FROM posthog_eventproperty
WHERE ctid = ANY(ARRAY(
        SELECT ctid FROM posthog_eventproperty
        WHERE coalesce(project_id, team_id) = %(project_id)s AND event = ANY(%(names)s)
        LIMIT %(batch)s))
  AND NOT EXISTS (
      SELECT 1 FROM posthog_eventdefinition ed
      WHERE coalesce(ed.project_id, ed.team_id) = %(project_id)s
        AND ed.name = posthog_eventproperty.event
        AND (ed.last_seen_at IS NULL OR ed.last_seen_at >= now() - make_interval(days => %(days)s)))
"""

# Mode 2c. Whole-tenant delete through the (team_id, property) index prefix.
DORMANT_DELETE = """
DELETE FROM posthog_eventproperty
WHERE ctid = ANY(ARRAY(
        SELECT ctid FROM posthog_eventproperty WHERE team_id = %(team_id)s LIMIT %(batch)s))
"""

# Mode 2c. Largest owners of the table from planner statistics, without touching the table.
DORMANT_TOP_TEAMS = """
SELECT v.team_id::int AS team_id, (f.freq * c.reltuples)::bigint AS est_rows
FROM pg_stats s
JOIN pg_class c ON c.relname = s.tablename
CROSS JOIN LATERAL unnest(s.most_common_vals::text::int[]) WITH ORDINALITY AS v(team_id, ord)
JOIN LATERAL unnest(s.most_common_freqs) WITH ORDINALITY AS f(freq, ord) ON f.ord = v.ord
WHERE s.tablename = 'posthog_eventproperty' AND s.attname = 'team_id'
ORDER BY est_rows DESC
LIMIT %(top_n)s
"""

DORMANT_EVENTDEFS = """
SELECT count(*) AS event_defs,
       count(*) FILTER (WHERE last_seen_at IS NULL) AS null_last_seen,
       max(last_seen_at) AS max_last_seen
FROM posthog_eventdefinition
WHERE team_id = %(team_id)s
"""

DORMANT_TEAM_ORG = """
SELECT t.created_at AS team_created_at,
       t.project_id,
       o.id AS organization_id,
       o.has_active_subscription,
       o.customer_id IS NOT NULL AS has_customer_id,
       o.is_pending_deletion,
       (o.usage -> 'events' ->> 'usage')::bigint AS events_usage
FROM posthog_team t
JOIN posthog_project p ON p.id = t.project_id
JOIN posthog_organization o ON o.id = p.organization_id
WHERE t.id = %(team_id)s
"""

DORMANT_HUMAN_ACTIVITY = """
SELECT (SELECT max(u.last_login)
        FROM posthog_organizationmembership m
        JOIN posthog_user u ON u.id = m.user_id
        WHERE m.organization_id = %(organization_id)s) AS last_login,
       (SELECT max(k.last_used_at)
        FROM posthog_personalapikey k
        JOIN posthog_organizationmembership m ON m.user_id = k.user_id
        WHERE m.organization_id = %(organization_id)s) AS last_api_key_use,
       (SELECT max(last_viewed_at) FROM posthog_insightviewed WHERE team_id = %(team_id)s) AS last_insight_view,
       (SELECT max(created_at) FROM posthog_activitylog WHERE team_id = %(team_id)s) AS last_activity_log,
       (SELECT count(*) FROM posthog_batchexport WHERE team_id = %(team_id)s AND NOT paused) AS active_batch_exports,
       (SELECT count(*) FROM posthog_survey
        WHERE team_id = %(team_id)s AND start_date IS NOT NULL AND end_date IS NULL) AS live_surveys,
       (SELECT count(*) FROM posthog_featureflag WHERE team_id = %(team_id)s AND active) AS active_flags
"""

# Persons DB (reader). posthog_person is hash-partitioned by team and has no created_at index, so the
# probe is bounded by the tenant's person count and runs under a short statement_timeout.
PERSONS_HAS_ROWS = "SELECT EXISTS (SELECT 1 FROM posthog_persondistinctid WHERE team_id = %(team_id)s)"
PERSONS_CREATED_RECENTLY = """
SELECT EXISTS (
    SELECT 1 FROM posthog_person
    WHERE team_id = %(team_id)s AND created_at > now() - make_interval(days => %(days)s))
"""

CLICKHOUSE_RECENT_EVENTS = """
SELECT count() FROM events
WHERE team_id = %(team_id)s AND timestamp > now() - INTERVAL %(days)s DAY
SETTINGS max_execution_time = 30
"""

HEALTH_TABLE_STATS = """
SELECT n_live_tup, n_dead_tup
FROM pg_stat_user_tables
WHERE relname = 'posthog_eventproperty'
"""
HEALTH_BLOCKED_PROPDEFS = """
SELECT count(*) FROM pg_stat_activity
WHERE usename = 'property-defs-rs' AND wait_event_type IN ('Lock', 'IO')
"""

VACUUM = "VACUUM (INDEX_CLEANUP ON, VERBOSE) posthog_eventproperty"
