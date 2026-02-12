import json

import httpx


class MCPClientError(Exception):
    pass


class MCPClient:
    """Minimal MCP client using JSON-RPC 2.0 over HTTP with Streamable HTTP transport."""

    def __init__(self, server_url: str, headers: dict[str, str] | None = None, session_id: str | None = None):
        self._server_url = server_url
        self._base_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **(headers or {}),
        }
        self._request_id = 0
        self._session_id: str | None = session_id
        self._client = httpx.AsyncClient(timeout=30.0)

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def close(self):
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

    def _parse_response(self, response: httpx.Response) -> dict:
        """Parse a JSON-RPC response, handling both JSON and SSE formats."""
        content_type = response.headers.get("content-type", "")

        if "text/event-stream" in content_type:
            return self._parse_sse_response(response.text)

        return response.json()

    def _parse_sse_response(self, text: str) -> dict:
        """Extract the JSON-RPC response from an SSE stream.

        SSE format is:
            event: message
            data: {"jsonrpc": "2.0", "result": {...}, "id": 1}
        """
        for line in text.splitlines():
            if line.startswith("data:"):
                data_str = line[len("data:") :].strip()
                if data_str:
                    return json.loads(data_str)
        raise MCPClientError("No data found in SSE response")

    async def _send_jsonrpc(self, method: str, params: dict | None = None) -> dict | None:
        """Send a JSON-RPC 2.0 request and return the result. For notifications (no id), returns None."""
        is_notification = method.startswith("notifications/")
        payload: dict = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        if not is_notification:
            payload["id"] = self._next_id()

        response = await self._client.post(self._server_url, json=payload, headers=self._headers)
        response.raise_for_status()

        # Capture session ID from server
        if session_id := response.headers.get("mcp-session-id"):
            self._session_id = session_id

        if is_notification:
            return None

        data = self._parse_response(response)
        if "error" in data:
            error = data["error"]
            raise MCPClientError(f"MCP error {error.get('code', '?')}: {error.get('message', 'Unknown error')}")
        return data.get("result")

    async def initialize(self) -> dict:
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
