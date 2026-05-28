"""The three arms compared, as declarative sandbox configs.

An "arm" decides how the agent reaches PostHog:
- ``cli``       : the posthog-cli binary on PATH (no MCP), discovered via the
                  steering block (AGENTS.md). This is the thing under test.
- ``mcp-tools`` : the MCP with every tool registered up front (the high-token load).
- ``mcp-exec``  : the MCP's single ``exec`` proxy (its own low-token mode).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Arm:
    key: str
    label: str
    mount_cli: bool
    """Mount the dev binary on PATH (sets SANDBOX_LOCAL_CLI_HOST_PATH for the run)."""
    suppress_mcp: bool
    """Don't register any MCP server for the agent (so it can only use the CLI)."""
    mcp_mode: str | None
    """MCP registration mode when not suppressed: 'tools' (all tools) or 'cli' (exec proxy)."""
    needs_steering: bool
    """Install the AGENTS.md steering block (`posthog-cli init`) so the agent discovers the CLI."""


ARMS: tuple[Arm, ...] = (
    Arm(key="cli", label="PostHog CLI", mount_cli=True, suppress_mcp=True, mcp_mode=None, needs_steering=True),
    Arm(
        key="mcp-tools",
        label="MCP (tools)",
        mount_cli=False,
        suppress_mcp=False,
        mcp_mode="tools",
        needs_steering=False,
    ),
    Arm(key="mcp-exec", label="MCP (exec)", mount_cli=False, suppress_mcp=False, mcp_mode="cli", needs_steering=False),
)
