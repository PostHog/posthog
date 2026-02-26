from __future__ import annotations

import time
from typing import Literal, Self

import structlog
from pydantic import BaseModel, Field, ValidationError

from posthog.schema import AssistantTool

from posthog.models import Team, User
from posthog.security.url_validation import is_url_allowed
from posthog.sync import database_sync_to_async

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolFatalError, MaxToolRetryableError
from ee.hogai.utils.types.base import AssistantState, NodePath

from .installations import _build_server_headers, _get_installations, _mark_needs_reauth_sync, _refresh_token_sync
from .mcp_client import MCPClient, MCPClientError

logger = structlog.get_logger(__name__)


class MCPToolProperty(BaseModel, extra="ignore"):
    type: str | list[str] = "any"
    description: str = ""

    @property
    def type_display(self) -> str:
        if isinstance(self.type, list):
            return " | ".join(self.type)
        return self.type


class MCPToolInputSchema(BaseModel, extra="ignore"):
    properties: dict[str, MCPToolProperty] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class MCPToolDefinition(BaseModel, extra="ignore"):
    name: str
    description: str = "No description"
    inputSchema: MCPToolInputSchema = Field(default_factory=MCPToolInputSchema)

    def format_for_llm(self) -> str:
        if not self.inputSchema.properties:
            params_str = "    (no parameters)"
        else:
            parts = []
            for param_name, param_info in self.inputSchema.properties.items():
                req = " (required)" if param_name in self.inputSchema.required else ""
                parts.append(f"    - {param_name}: {param_info.type_display}{req} — {param_info.description}")
            params_str = "\n".join(parts)
        return f"- **{self.name}**: {self.description}\n  Parameters:\n{params_str}"


class CallMCPServerToolArgs(BaseModel):
    server_url: str = Field(description="URL of the MCP server to call")
    tool_name: str = Field(
        description="Name of the tool to invoke on the server, or '__list_tools__' to discover available tools"
    )
    arguments: dict = Field(default_factory=dict, description="Arguments to pass to the tool")


class CallMCPServerTool(MaxTool):
    name: Literal[AssistantTool.CALL_MCP_SERVER] = AssistantTool.CALL_MCP_SERVER
    description: str = "No MCP servers installed."
    args_schema: type[BaseModel] = CallMCPServerToolArgs

    _allowed_server_urls: set[str]
    _installations: list
    _installations_by_url: dict[str, dict]
    _server_headers: dict[str, dict[str, str]]

    @classmethod
    async def create_tool_class(
        cls,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...] | None = None,
        state: AssistantState | None = None,
        config=None,
        context_manager: AssistantContextManager | None = None,
    ) -> Self:
        installations = await database_sync_to_async(_get_installations)(team, user)

        if not installations:
            description = "No MCP servers are installed. This tool is not available."
        else:
            server_lines = "\n".join(f"- {inst['display_name']}: {inst['url']}" for inst in installations)
            description = (
                "Call a tool on a user-installed MCP server. "
                "The user has the following MCP servers installed:\n"
                f"{server_lines}\n\n"
                "To discover what tools a server offers, call this with tool_name='__list_tools__' "
                "and the server_url. Then use the returned tool definitions to make actual tool calls."
            )

        allowed_urls = {inst["url"] for inst in installations}
        server_headers = _build_server_headers(installations)

        instance = cls(
            team=team,
            user=user,
            node_path=node_path,
            state=state,
            config=config,
            context_manager=context_manager,
            description=description,
        )
        instance._allowed_server_urls = allowed_urls
        instance._installations = installations
        instance._installations_by_url = {inst["url"]: inst for inst in installations}
        instance._server_headers = server_headers
        return instance

    async def _arun_impl(self, server_url: str, tool_name: str, arguments: dict | None = None) -> tuple[str, None]:
        self._validate_server_url(server_url)
        await self._try_proactive_token_refresh(server_url)

        try:
            result = await self._call_server(server_url, tool_name, arguments)
            return result, None
        except MCPClientError as e:
            raise MaxToolRetryableError(f"MCP server error: {e}")

    async def _call_server(self, server_url: str, tool_name: str, arguments: dict | None) -> str:
        try:
            return await self._attempt_call(server_url, tool_name, arguments)
        except MCPClientError:
            # Refresh auth in case that was the issue and retry the tool call once.
            await self._refresh_auth_or_mark_reauth(server_url)
            return await self._attempt_call(server_url, tool_name, arguments)

    async def _attempt_call(self, server_url: str, tool_name: str, arguments: dict | None) -> str:
        headers = self._server_headers.get(server_url)
        client = MCPClient(server_url, headers=headers)
        try:
            # We build up and tear down the client session with every request.
            # This lets us use the same code in cloud, our backend, and when proxying via the server.
            await client.initialize()
            return await self._execute_mcp_call(client, server_url, tool_name, arguments)
        finally:
            await client.close()

    async def _execute_mcp_call(
        self, client: MCPClient, server_url: str, tool_name: str, arguments: dict | None
    ) -> str:
        if tool_name == "__list_tools__":
            return await self._get_tool_list(client, server_url)
        else:
            return await self._call_tool(client, server_url, tool_name, arguments)

    async def _get_tool_list(self, client: MCPClient, server_url: str) -> str:
        raw_tools = await client.list_tools()
        if not raw_tools:
            return "This MCP server has no tools available."

        tools: list[MCPToolDefinition] = []
        for raw in raw_tools:
            try:
                tools.append(MCPToolDefinition.model_validate(raw))
            except ValidationError:
                logger.warning("Skipping malformed tool definition from MCP server", server_url=server_url, raw=raw)

        if not tools:
            return "This MCP server has no tools available."

        formatted = "\n\n".join(t.format_for_llm() for t in tools)
        return f"Tools available on {server_url}:\n\n{formatted}"

    async def _call_tool(self, client: MCPClient, server_url: str, tool_name: str, arguments: dict | None) -> str:
        return await client.call_tool(tool_name, arguments or {})

    def _validate_server_url(self, server_url: str) -> None:
        if server_url not in self._allowed_server_urls:
            raise MaxToolFatalError(
                f"Server URL '{server_url}' is not in the user's installed MCP servers. "
                f"Allowed URLs: {', '.join(sorted(self._allowed_server_urls))}"
            )
        allowed, error = is_url_allowed(server_url)
        if not allowed:
            raise MaxToolFatalError(f"MCP server URL blocked by security policy")

    async def _try_proactive_token_refresh(self, server_url: str) -> None:
        if not self._is_token_expiring(server_url):
            return
        try:
            await self._refresh_token_for_server(server_url)
        except Exception:
            logger.warning("Proactive token refresh failed, continuing with current token", server_url=server_url)

    async def _refresh_auth_or_mark_reauth(self, server_url: str) -> None:
        try:
            await self._refresh_token_for_server(server_url)
        except Exception:
            inst = self._get_installation(server_url)
            await database_sync_to_async(_mark_needs_reauth_sync)(inst["id"])
            raise MaxToolFatalError(
                f"Authentication failed for {server_url} and token refresh failed. "
                "Ask the user to re-authenticate with this MCP server in the MCP store settings page."
            )

    def _is_token_expiring(self, server_url: str) -> bool:
        inst = self._get_installation(server_url)
        sensitive = inst.get("sensitive_configuration") or {}

        try:
            token_retrieved_at = float(sensitive.get("token_retrieved_at", 0))
            expires_in = float(sensitive.get("expires_in", 0))
        except (TypeError, ValueError):
            return False

        if not token_retrieved_at or not expires_in:
            return False

        # Refreshing half way through expiry to be safe
        return time.time() > token_retrieved_at + (expires_in / 2)

    async def _refresh_token_for_server(self, server_url: str) -> None:
        inst = self._get_installation(server_url)
        sensitive = inst.get("sensitive_configuration") or {}
        refresh_token = sensitive.get("refresh_token")
        if not refresh_token:
            raise MaxToolFatalError(
                f"No refresh token available for {server_url}. Ask the user to re-authenticate with this MCP server."
            )

        updated = await database_sync_to_async(_refresh_token_sync)(inst)

        inst["sensitive_configuration"] = updated
        self._installations_by_url[server_url] = inst
        self._server_headers[server_url] = {"Authorization": f"Bearer {updated['access_token']}"}

    def _get_installation(self, server_url: str) -> dict:
        inst = self._installations_by_url.get(server_url)
        if not inst:
            raise MaxToolFatalError(f"No installation found for {server_url}")
        return inst
