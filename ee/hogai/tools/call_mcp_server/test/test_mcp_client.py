from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from ee.hogai.tools.call_mcp_server.mcp_client import MCPClient, MCPClientError


def _teardown_error() -> BaseException:
    # Shape of what the MCP SDK raises when an upstream HTTP error reaches its task group.
    return ExceptionGroup("unhandled errors in a TaskGroup", [RuntimeError("server returned 401")])


class TestMCPClient(IsolatedAsyncioTestCase):
    async def test_close_swallows_teardown_exception_group(self):
        client = MCPClient("https://mcp.example.com")
        client._stack.aclose = AsyncMock(side_effect=_teardown_error())

        await client.close()

    async def test_failed_connect_with_failing_teardown_raises_client_error(self):
        client = MCPClient("https://mcp.example.com")
        client._stack.aclose = AsyncMock(side_effect=_teardown_error())

        with (
            patch.object(MCPClient, "_connect_streamable_http", AsyncMock(side_effect=RuntimeError("boom"))),
            patch.object(MCPClient, "_connect_sse", AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            with self.assertRaises(MCPClientError):
                await client.initialize()
