from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from django.test import SimpleTestCase

from mcp import types
from mcp.server.lowlevel import Server
from mcp.shared.memory import create_connected_server_and_client_session

from ee.hogai.tools.call_mcp_server.mcp_client import MCPClient, MCPInvalidToolResultError


def _make_server(call_tool_result: types.CallToolResult) -> Server:
    server: Server = Server("test")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="search",
                inputSchema={"type": "object"},
                outputSchema={"type": "object", "properties": {"hits": {"type": "array"}}, "required": ["hits"]},
            )
        ]

    # Raw handler so the server sends the result as is, without the SDK's server-side output checks.
    async def call_tool(_req: types.CallToolRequest) -> types.ServerResult:
        return types.ServerResult(call_tool_result)

    server.request_handlers[types.CallToolRequest] = call_tool
    return server


@asynccontextmanager
async def _connected_client(call_tool_result: types.CallToolResult) -> AsyncIterator[MCPClient]:
    async with create_connected_server_and_client_session(_make_server(call_tool_result)) as session:
        client = MCPClient("https://mcp.example.com/mcp")
        client._session = session
        yield client


class TestMCPClientCallTool(SimpleTestCase):
    async def test_returns_text_when_output_schema_declared_but_structured_content_missing(self) -> None:
        async with _connected_client(
            types.CallToolResult(content=[types.TextContent(type="text", text="found 2 hits")])
        ) as client:
            self.assertEqual(await client.call_tool("search", {"q": "x"}), "found 2 hits")

    async def test_returns_text_when_structured_content_does_not_match_output_schema(self) -> None:
        async with _connected_client(
            types.CallToolResult(
                content=[types.TextContent(type="text", text="found 2 hits")], structuredContent={"other": 1}
            )
        ) as client:
            self.assertEqual(await client.call_tool("search", {"q": "x"}), "found 2 hits")

    async def test_malformed_result_raises_invalid_tool_result_error(self) -> None:
        async with _connected_client(types.CallToolResult.model_construct(content="not a list")) as client:  # type: ignore[arg-type]
            with self.assertRaises(MCPInvalidToolResultError):
                await client.call_tool("search", {"q": "x"})
