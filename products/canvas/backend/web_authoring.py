"""What the web app may not do to canvases: people create and edit them through the PostHog MCP server."""

from typing import Any

# The web app views canvases but does not author them, so its create, edit, hosted generation and agent
# paths are closed. Only session callers are restricted: MCP clients, PostHog Desktop, scouts, sandboxes
# and workload tokens never use a session.
SESSION_BLOCKED_ACTIONS = frozenset(
    {
        "create",
        "publish",
        "edit",
        "draft",
        "promote",
        "revert",
        "publish_current_version",
        "publish_layout",
        "patch_layout",
        "request_fix",
        "request_agent",
    }
)
# Linking a generation task is how the web app starts a hosted generation or a hosted edit run.
SESSION_BLOCKED_UPDATE_FIELDS = frozenset({"generation_task_id"})
# A retry queues a build whose completion can publish content the web app could not publish itself.
# The other build actions (pin, unpin, cancel) do not publish anything.
SESSION_BLOCKED_BUILD_ACTIONS = frozenset({"retry"})


def blocks_session_action(action: str | None, data: Any) -> bool:
    """Whether a web app session may not run this viewset action."""
    if action in SESSION_BLOCKED_ACTIONS:
        return True
    if action == "partial_update" and isinstance(data, dict):
        return not SESSION_BLOCKED_UPDATE_FIELDS.isdisjoint(data)
    if action == "build_action" and isinstance(data, dict):
        # The body is not validated yet, and an unhashable value would raise on the membership check.
        build_action = data.get("action")
        return isinstance(build_action, str) and build_action in SESSION_BLOCKED_BUILD_ACTIONS
    return False
