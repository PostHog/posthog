from __future__ import annotations

from contextlib import AsyncExitStack
from datetime import timedelta

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent


class MCPClientError(Exception):
    pass


CLIENT_TIMEOUT = 60.0


class MCPClient:
    """MCP client wrapping the official SDK with Streamable HTTP → SSE fallback."""

    def __init__(self, server_url: str, headers: dict[str, str] | None = None):
        self._server_url = server_url
        self._headers = headers
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def initialize(self) -> None:
        try:
            await self._connect_streamable_http()
            return
        except Exception:
            await self._stack.aclose()
            self._stack = AsyncExitStack()

        try:
            await self._connect_sse()
        except Exception:
            await self._stack.aclose()
            raise MCPClientError("Failed to connect to MCP server")

    async def _connect_streamable_http(self) -> None:
        http_client = await self._stack.enter_async_context(
            httpx.AsyncClient(headers=self._headers, timeout=CLIENT_TIMEOUT)
        )
        read, write, _get_session_id = await self._stack.enter_async_context(
            streamable_http_client(self._server_url, http_client=http_client)
        )
        session = await self._stack.enter_async_context(
            ClientSession(read, write, read_timeout_seconds=timedelta(seconds=CLIENT_TIMEOUT))
        )
        await session.initialize()
        self._session = session

    async def _connect_sse(self) -> None:
        read, write = await self._stack.enter_async_context(
            sse_client(self._server_url, headers=self._headers, timeout=CLIENT_TIMEOUT, sse_read_timeout=CLIENT_TIMEOUT)
        )
        session = await self._stack.enter_async_context(
            ClientSession(read, write, read_timeout_seconds=timedelta(seconds=CLIENT_TIMEOUT))
        )
        await session.initialize()
        self._session = session

    async def close(self) -> None:
        await self._stack.aclose()

    async def list_tools(self) -> list[dict]:
        if self._session is None:
            raise MCPClientError("Client not initialized. Call initialize() first.")
        try:
            result = await self._session.list_tools()
        except Exception:
            raise MCPClientError("Failed to list tools")
        return [tool.model_dump(by_alias=True) for tool in result.tools]

    async def call_tool(self, tool_name: str, arguments: dict | None = None) -> str:
        if self._session is None:
            raise MCPClientError("Client not initialized. Call initialize() first.")
        try:
            result = await self._session.call_tool(tool_name, arguments or {})
        except Exception:
            raise MCPClientError("Failed to call tool")

        if result.isError:
            text_parts = [c.text for c in result.content if isinstance(c, TextContent)]
            error_text = "\n".join(text_parts) if text_parts else "Tool returned an error"
            raise MCPClientError(error_text[:500])

        text_parts = [c.text for c in result.content if isinstance(c, TextContent)]
        return "\n".join(text_parts) if text_parts else str(result.content)
