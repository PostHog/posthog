"""Pytest fixtures for the MCP eval suite.

Unlike ``ee/hogai/eval/ci``, the MCP eval does *not* go through a Django
test database — it talks to a real PostHog server over HTTP via the MCP
Cloudflare worker. The developer (or CI) is responsible for starting Django
and providing a personal API key out of band; see ``README.md``.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from .harness import MCPServer, start_mcp_server


@pytest.fixture(scope="session")
def mcp_server() -> Generator[MCPServer, None, None]:
    server, process = start_mcp_server()
    try:
        yield server
    finally:
        process.stop()
