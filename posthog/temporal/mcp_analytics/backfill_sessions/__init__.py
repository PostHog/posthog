from posthog.temporal.mcp_analytics.backfill_sessions.activities import aggregate_and_upsert_mcp_sessions
from posthog.temporal.mcp_analytics.backfill_sessions.workflow import BackfillMCPSessionsWorkflow

MCP_ANALYTICS_BACKFILL_SESSIONS_WORKFLOWS = [
    BackfillMCPSessionsWorkflow,
]

MCP_ANALYTICS_BACKFILL_SESSIONS_ACTIVITIES = [aggregate_and_upsert_mcp_sessions]
