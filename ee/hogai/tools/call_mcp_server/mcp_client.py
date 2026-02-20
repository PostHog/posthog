import json
import asyncio
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import httpx


class MCPClientError(Exception):
    pass


class MCPClient:
    """MCP client supporting both Streamable HTTP and SSE transports.

    Tries Streamable HTTP first (POST to server URL). If the server returns
    404 or 405, falls back to the legacy SSE transport (GET to discover a
    message endpoint, then POST JSON-RPC there).
    """

    def __init__(self, server_url: str, headers: dict[str, str] | None = None, session_id: str | None = None):
        self._server_url = server_url
        self._message_url = server_url
        self._base_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **(headers or {}),
        }
        self._request_id = 0
        self._session_id: str | None = session_id
        self._client = httpx.AsyncClient(timeout=30.0)

        # SSE transport state
        self._sse_response: httpx.Response | None = None
        self._sse_lines: AsyncIterator[str] | None = None
        self._sse_reader_task: asyncio.Task | None = None
        self._pending_responses: dict[int, asyncio.Future] = {}

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def close(self) -> None:
        if self._sse_reader_task:
            self._sse_reader_task.cancel()
            try:
                await self._sse_reader_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._sse_response:
            await self._sse_response.aclose()
        await self._client.aclose()

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    @property
    def _headers(self) -> dict[str, str]:
        headers = dict(self._base_headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _resolve_url(self, endpoint: str) -> str:
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return endpoint
        parsed = urlparse(self._server_url)
        return f"{parsed.scheme}://{parsed.netloc}{endpoint}"

    def _parse_response(self, response: httpx.Response) -> dict:
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return self._parse_sse_data(response.text)
        return response.json()

    def _parse_sse_data(self, text: str) -> dict:
        for line in text.splitlines():
            if line.startswith("data:"):
                data_str = line[len("data:") :].strip()
                if data_str:
                    return json.loads(data_str)
        raise MCPClientError("No data found in SSE response")

    # -- SSE transport helpers --

    async def _connect_sse_transport(self) -> None:
        headers = {k: v for k, v in self._base_headers.items() if k != "Content-Type"}
        headers["Accept"] = "text/event-stream"

        req = self._client.build_request("GET", self._server_url, headers=headers)
        self._sse_response = await self._client.send(req, stream=True)
        self._sse_response.raise_for_status()

        self._sse_lines = self._sse_response.aiter_lines()
        endpoint = await self._read_sse_endpoint()
        self._message_url = self._resolve_url(endpoint)

        self._sse_reader_task = asyncio.create_task(self._sse_reader_loop())

    async def _read_sse_endpoint(self) -> str:
        assert self._sse_lines is not None
        event_type: str | None = None
        async for raw_line in self._sse_lines:
            line = raw_line.strip()
            if not line:
                event_type = None
                continue
            if line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("data:") and event_type == "endpoint":
                return line[len("data:") :].strip()
        raise MCPClientError("SSE stream closed without providing endpoint")

    async def _sse_reader_loop(self) -> None:
        assert self._sse_lines is not None
        event_type: str | None = None
        try:
            async for raw_line in self._sse_lines:
                line = raw_line.strip()
                if not line:
                    event_type = None
                    continue
                if line.startswith("event:"):
                    event_type = line[len("event:") :].strip()
                elif line.startswith("data:") and event_type == "message":
                    data_str = line[len("data:") :].strip()
                    if not data_str:
                        continue
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    req_id = data.get("id")
                    if req_id is not None and req_id in self._pending_responses:
                        self._pending_responses[req_id].set_result(data)
        except (httpx.ReadError, asyncio.CancelledError):
            pass

    # -- JSON-RPC transport --

    async def _send_jsonrpc(self, method: str, params: dict | None = None) -> dict | None:
        is_notification = method.startswith("notifications/")
        payload: dict = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        if not is_notification:
            payload["id"] = self._next_id()

        future: asyncio.Future | None = None
        if self._sse_response and not is_notification:
            future = asyncio.get_running_loop().create_future()
            self._pending_responses[payload["id"]] = future

        try:
            response = await self._client.post(self._message_url, json=payload, headers=self._headers)
            response.raise_for_status()
        except Exception:
            if future:
                self._pending_responses.pop(payload["id"], None)
            raise

        if session_id := response.headers.get("mcp-session-id"):
            self._session_id = session_id

        if is_notification:
            return None

        # SSE transport: always read responses from the event stream
        if future:
            try:
                data = await asyncio.wait_for(future, timeout=30.0)
            except TimeoutError:
                raise MCPClientError("Timeout waiting for response on SSE stream")
            finally:
                self._pending_responses.pop(payload["id"], None)
            if "error" in data:
                error = data["error"]
                raise MCPClientError(f"MCP error {error.get('code', '?')}: {error.get('message', 'Unknown error')}")
            return data.get("result")

        # Streamable HTTP: read response from POST body
        data = self._parse_response(response)
        if "error" in data:
            error = data["error"]
            raise MCPClientError(f"MCP error {error.get('code', '?')}: {error.get('message', 'Unknown error')}")
        return data.get("result")

    # -- Public API --

    async def initialize(self) -> dict:
        try:
            return await self._do_initialize()
        except httpx.HTTPStatusError as e:
            if e.response.status_code not in (404, 405):
                raise
            # Fall back to SSE transport
            await self._connect_sse_transport()
            return await self._do_initialize()

    async def _do_initialize(self) -> dict:
        result = await self._send_jsonrpc(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "posthog-max", "version": "1.0.0"},
            },
        )
        if result is None:
            raise MCPClientError("MCP server returned no result for initialize")
        await self._send_jsonrpc("notifications/initialized")
        return result

    async def list_tools(self) -> list[dict]:
        result = await self._send_jsonrpc("tools/list")
        if result is None:
            raise MCPClientError("MCP server returned no result for tools/list")
        return result.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: dict | None = None) -> str:
        result = await self._send_jsonrpc(
            "tools/call",
            {"name": tool_name, "arguments": arguments or {}},
        )
        if result is None:
            raise MCPClientError("MCP server returned no result for tools/call")

        content_parts = result.get("content", [])
        text_parts = [part["text"] for part in content_parts if part.get("type") == "text" and "text" in part]
        if not text_parts:
            return str(result)
        return "\n".join(text_parts)
