from __future__ import annotations

MCP_PORT = 18787
"""Non-default port to avoid conflicts with a running dev MCP server."""

DJANGO_LIVE_PORT = 18000
"""Non-default port for the in-process Django server."""

LLM_GATEWAY_PORT = 13308
"""Non-default port to avoid conflicts with a running dev LLM gateway."""

NGROK_WEB_PORT = 14040
"""Dedicated ngrok agent API port, so the harness never adopts or collides with
a developer's already-running ngrok agent on the default 4040."""
