"""Canvas MCP tools: PostHog MCP tools a canvas may call as the viewer (ph.tools).

The tool runs on the PostHog MCP server with a short-lived token minted for
the viewer, so the canvas reuses the tool's own input handling, the viewer's
permissions, approval policies and activity logging. A new capability is one
line in the allowlist, not a new action verb.

A canvas reads with ph.tools.read, which takes read-only tools only, and
writes with ph.tools.call, which the host runs from a click and confirms
with the viewer first.
"""

from typing import Any
from uuid import UUID

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.mcp_tool_definitions import McpToolDefinition, get_mcp_tool_definitions

from products.webmcp.backend.facade import api as webmcp_facade
from products.webmcp.backend.facade.contracts import CallToolInput, McpServerError, McpServerTimeout

logger = structlog.get_logger(__name__)

# Rollout gate, evaluated per team. Fails closed because every call acts with the viewer's permissions.
CANVAS_MCP_TOOLS_FLAG = "canvas-mcp-tools"

# The tools a canvas may declare. Every entry must be a catalogued MCP tool; a
# test checks that. Add a tool here only when one call to it is safe to run
# from a button, because the viewer confirms a single call, not a sequence.
CANVAS_MCP_TOOL_ALLOWLIST: frozenset[str] = frozenset(
    {
        "feature-flag-get-all",
        "feature-flag-get-definition",
        "feature-flag-enable",
        "feature-flag-disable",
        "feature-flag-set-release-condition-rollout",
    }
)


class CanvasMcpToolError(Exception):
    """The tool ran and failed, or the MCP server could not run it. The message is safe to show the viewer."""

    def __init__(self, message: str, *, server_unavailable: bool = False, outcome_unknown: bool = False) -> None:
        super().__init__(message)
        self.server_unavailable = server_unavailable
        # A write timed out after the server received it, so it can still apply.
        self.outcome_unknown = outcome_unknown


@frozen
class CanvasMcpToolResult:
    result: dict[str, Any]


def canvas_mcp_tools_enabled(team_uuid: UUID | str) -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                CANVAS_MCP_TOOLS_FLAG,
                str(team_uuid),
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("canvas_mcp_tools_flag_check_failed")
        return False


def canvas_mcp_tool(name: str) -> McpToolDefinition | None:
    """The tool's catalogue entry when canvases may call it, else None."""
    if name not in CANVAS_MCP_TOOL_ALLOWLIST:
        return None
    return get_mcp_tool_definitions().get(name)


def canvas_mcp_tools() -> list[McpToolDefinition]:
    definitions = get_mcp_tool_definitions()
    return [definitions[name] for name in sorted(CANVAS_MCP_TOOL_ALLOWLIST) if name in definitions]


def call_canvas_mcp_tool(team_id: int, user_id: int, tool: str, arguments: dict[str, Any]) -> CanvasMcpToolResult:
    """Run one allowlisted tool as the viewer. Raises CanvasMcpToolError when it fails."""
    try:
        outcome = webmcp_facade.call_tool(
            CallToolInput(user_id=user_id, team_id=team_id, tool=tool, arguments=arguments)
        )
    except McpServerTimeout as error:
        definition = canvas_mcp_tool(tool)
        if definition is not None and not definition.read_only:
            logger.warning("canvas_mcp_tool_write_timed_out", tool=tool)
            raise CanvasMcpToolError(
                "The tool did not answer in time, and the change can still apply. "
                "Load the current state before you try again.",
                outcome_unknown=True,
            ) from error
        logger.warning("canvas_mcp_tool_server_error", tool=tool, error=str(error))
        raise CanvasMcpToolError(
            "The PostHog MCP server could not run this tool. Try again.", server_unavailable=True
        ) from error
    except McpServerError as error:
        logger.warning("canvas_mcp_tool_server_error", tool=tool, error=str(error))
        raise CanvasMcpToolError(
            "The PostHog MCP server could not run this tool. Try again.", server_unavailable=True
        ) from error
    if outcome.is_error:
        raise CanvasMcpToolError(outcome.text or f'The tool "{tool}" failed.')
    if outcome.structured_content is None:
        raise CanvasMcpToolError(f'The tool "{tool}" returned no JSON result.')
    return CanvasMcpToolResult(result=outcome.structured_content)
