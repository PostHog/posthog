# MCP and AI events carry a $session_id but do not describe a website or app visit. Every query that writes session
# rows (the v2 and v3 materialized views and backfills) must apply this filter, so a backfill builds the same rows.
SESSIONS_EXCLUDED_EVENT_PREFIXES = ("$mcp_", "$ai_")

SESSIONS_EVENT_FILTER_SQL = "NOT ({})".format(
    " OR ".join(f"startsWith(event, '{prefix}')" for prefix in SESSIONS_EXCLUDED_EVENT_PREFIXES)
)
