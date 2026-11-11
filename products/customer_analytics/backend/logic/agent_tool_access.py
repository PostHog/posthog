from typing import Literal

AgentToolAccess = Literal["read", "write", "other"]

# Verbs inside a hyphenated MCP tool name, such as `feature-flag-get-all` or `dashboard-create-tile`.
WRITE_VERBS = frozenset(
    {
        "add",
        "archive",
        "create",
        "delete",
        "destroy",
        "disable",
        "duplicate",
        "enable",
        "launch",
        "partial",
        "remove",
        "restore",
        "set",
        "update",
        "upsert",
    }
)
READ_VERBS = frozenset({"count", "explain", "get", "list", "preview", "query", "read", "results", "retrieve", "search"})
READ_TOOLS = frozenset({"execute-sql", "read-data-schema"})


def classify_agent_tool_access(tool: str | None) -> AgentToolAccess:
    """Whether an MCP tool changes data. A write verb wins, so `dashboard-get-and-update` counts as a write."""
    name = (tool or "").lower()
    if name in READ_TOOLS:
        return "read"
    verbs = set(name.split("-"))
    if verbs & WRITE_VERBS:
        return "write"
    if verbs & READ_VERBS:
        return "read"
    return "other"
