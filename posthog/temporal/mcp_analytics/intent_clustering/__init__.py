"""MCP analytics intent clustering — Temporal workflow exports.

This module is the registration seam for the ``mcp-analytics-task-queue``
worker. Workflows and activities are added here as subsequent PRs land them;
the empty lists below are intentional in PR #4 so the worker registers the
queue without yet exposing any handlers.
"""

MCP_ANALYTICS_INTENT_CLUSTERING_WORKFLOWS: list = []
MCP_ANALYTICS_INTENT_CLUSTERING_ACTIVITIES: list = []
