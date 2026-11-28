from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from datetime import timedelta

import httpx
import structlog
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

from products.mcp_store.backend.url_policy import trust_environment_proxy

logger = structlog.get_logger(__name__)


class MCPClientError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


CLIENT_TIMEOUT = 60.0


def _find_http_status_error(error: BaseException) -> httpx.HTTPStatusError | None:
    if isinstance(error, httpx.HTTPStatusError):
        return error
    if isinstance(error, BaseExceptionGroup):
        for inner in error.exceptions:
            if status_error := _find_http_status_error(inner):
                return status_error
    return None


def _transport_error(error: Exception) -> MCPClientError:
    status_error = _find_http_status_error(error)
    if status_error is None:
        client_error = MCPClientError("MCP server request failed")
    else:
        status_code = status_error.response.status_code
        client_error = MCPClientError(f"MCP server responded with HTTP {status_code}", status_code=status_code)
    client_error.__cause__ = error
    return client_error


def _cancelled_by_caller() -> bool:
    # anyio undoes the cancellations its own cancel scopes made once they exit, so after the transport closes
    # any cancellation still requested on this task came from the caller.
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


class MCPClient:
    """MCP client wrapping the official SDK with Streamable HTTP → SSE fallback."""

    def __init__(self, server_url: str, headers: dict[str, str] | None = None, team_id: int | None = None):
        self._server_url = server_url
        self._headers = headers
        self._team_id = team_id
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def initialize(self) -> None:
        try:
            await self._connect_streamable_http()
            return
        except Exception:
            streamable_error = await self._close_transport()
        except asyncio.CancelledError:
            streamable_error = await self._close_transport()
            if streamable_error is None or _cancelled_by_caller():
                raise

        try:
            await self._connect_sse()
        except Exception as e:
            await self._close_transport()
            sse_error = _transport_error(e)
            # An SSE-only server can reject the Streamable HTTP POST with a 405 before it checks credentials.
            if sse_error.status_code == 401:
                raise sse_error
            raise streamable_error or MCPClientError("Failed to connect to MCP server")

    async def _connect_streamable_http(self) -> None:
        http_client = await self._stack.enter_async_context(
            httpx.AsyncClient(
                headers=self._headers,
                timeout=CLIENT_TIMEOUT,
                trust_env=trust_environment_proxy(self._server_url, self._team_id),
            )
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

    async def _close_transport(self) -> MCPClientError | None:
        """Close the transport and return the error of a failed request, if one failed.

        The Streamable HTTP transport sends each request in an anyio task group.
        A failed request, such as an HTTP 401, cancels the pending session call, and its error only surfaces
        here as an ExceptionGroup.
        """
        stack, self._stack = self._stack, AsyncExitStack()
        self._session = None
        try:
            await stack.aclose()
        except Exception as e:
            return _transport_error(e)
        return None

    async def _raise_transport_error(self) -> None:
        transport_error = await self._close_transport()
        if transport_error is not None and not _cancelled_by_caller():
            raise transport_error

    async def close(self) -> None:
        transport_error = await self._close_transport()
        if transport_error is not None:
            # Callers close in a finally block, so a raise here would replace the call's own result or error.
            logger.warning("MCP transport failed while closing", error=str(transport_error))

    async def list_tools(self) -> list[dict]:
        if self._session is None:
            raise MCPClientError("Client not initialized. Call initialize() first.")
        try:
            result = await self._session.list_tools()
        except asyncio.CancelledError:
            await self._raise_transport_error()
            raise
        except Exception:
            raise MCPClientError("Failed to list tools")
        return [tool.model_dump(by_alias=True) for tool in result.tools]

    async def call_tool(self, tool_name: str, arguments: dict | None = None) -> str:
        if self._session is None:
            raise MCPClientError("Client not initialized. Call initialize() first.")
        try:
            result = await self._session.call_tool(tool_name, arguments or {})
        except asyncio.CancelledError:
            await self._raise_transport_error()
            raise
        except Exception:
            raise MCPClientError("Failed to call tool")

        if result.isError:
            text_parts = [c.text for c in result.content if isinstance(c, TextContent)]
            error_text = "\n".join(text_parts) if text_parts else "Tool returned an error"
            raise MCPClientError(error_text[:500])

        text_parts = [c.text for c in result.content if isinstance(c, TextContent)]
        return "\n".join(text_parts) if text_parts else str(result.content)
