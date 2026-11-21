"""MCP Wrapped, registered against ``settings.MCPA_TASK_QUEUE`` by ``start_temporal_worker``."""

from posthog.temporal.mcp_analytics.wrapped.activities import (
    discover_wrapped_team_ids_activity,
    generate_wrapped_activity,
)
from posthog.temporal.mcp_analytics.wrapped.coordinator import MCPWrappedCoordinatorWorkflow

MCP_ANALYTICS_WRAPPED_WORKFLOWS = [MCPWrappedCoordinatorWorkflow]

MCP_ANALYTICS_WRAPPED_ACTIVITIES = [discover_wrapped_team_ids_activity, generate_wrapped_activity]

__all__ = [
    "MCP_ANALYTICS_WRAPPED_ACTIVITIES",
    "MCP_ANALYTICS_WRAPPED_WORKFLOWS",
    "MCPWrappedCoordinatorWorkflow",
    "discover_wrapped_team_ids_activity",
    "generate_wrapped_activity",
]
