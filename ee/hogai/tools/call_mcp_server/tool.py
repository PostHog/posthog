from __future__ import annotations

import json
from typing import Literal, Self

import structlog
from pydantic import BaseModel, Field, ValidationError

from posthog.schema import AssistantTool

from posthog.models import Team, User
from posthog.security.url_validation import is_url_allowed
from posthog.sync import database_sync_to_async

from products.mcp_store.backend.oauth import is_token_expiring

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolFatalError, MaxToolRetryableError
from ee.hogai.utils.types.base import AssistantState, NodePath

from .installations import (
    _build_server_headers,
    _get_cached_tools,
    _get_installations,
    _get_tool_approval_states,
    _mark_needs_reauth_sync,
    _refresh_token_sync,
)
from .mcp_client import MCPClient, MCPClientError

_APPROVAL_DEFAULT = "needs_approval"

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
    # {server_url: {tool_name: approval_state}} — lazily populated to minimize DB reads; also seeded by _get_cached_tool_list to avoid double lookup when calling __list_tools__
    _approval_cache: dict[str, dict[str, str]]

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
        instance._approval_cache = {}
        return instance

    async def _get_approval_states(self, server_url: str) -> dict[str, str]:
        cached = self._approval_cache.get(server_url)
        if cached is not None:
            return cached
        inst = self._get_installation(server_url)
        states = await database_sync_to_async(_get_tool_approval_states)(str(inst["id"]))
        self._approval_cache[server_url] = states
        return states

    async def _resolve_approval_state(self, server_url: str, tool_name: str) -> str:
        states = await self._get_approval_states(server_url)
        return states.get(tool_name, _APPROVAL_DEFAULT)

    async def is_dangerous_operation(
        self, *, server_url: str, tool_name: str, arguments: dict | None = None, **_kwargs
    ) -> bool:
        # Tool discovery should never require approval
        if tool_name == "__list_tools__":
            return False
        # Unknown server_url will be rejected by _validate_server_url during
        # execution; don't gate approval on it.
        if server_url not in self._allowed_server_urls:
            return False
        state = await self._resolve_approval_state(server_url, tool_name)
        return state == "needs_approval"

    async def format_dangerous_operation_preview(
        self, *, server_url: str, tool_name: str, arguments: dict | None = None, **_kwargs
    ) -> str:
        inst = self._installations_by_url.get(server_url, {})
        display = inst.get("display_name") or server_url
        if arguments:
            try:
                args_str = json.dumps(arguments, indent=2, default=str)
            except (TypeError, ValueError):
                args_str = repr(arguments)
            args_block = f"\n\n```json\n{args_str}\n```"
        else:
            args_block = "\n\n*(no arguments)*"
        return f"Max wants to call **{tool_name}** on **{display}**.{args_block}"

    async def _arun_impl(self, server_url: str, tool_name: str, arguments: dict | None = None) -> tuple[str, None]:
        self._validate_server_url(server_url)

        # Use per-installation cache for `__list_tools__` if available to avoid unnecessary server calls and token refreshes.
        if tool_name == "__list_tools__":
            cached = await self._get_cached_tool_list(server_url)
            if cached is not None:
                return cached, None

        await self._try_proactive_token_refresh(server_url)

        try:
            result = await self._call_server(server_url, tool_name, arguments)
            return result, None
        except MCPClientError as e:
            raise MaxToolRetryableError(f"MCP server error: {e}")

    async def _get_cached_tool_list(self, server_url: str) -> str | None:
        """Return a formatted tool list from Postgres, or None if the cache is empty."""
        inst = self._get_installation(server_url)
        rows = await database_sync_to_async(_get_cached_tools)(str(inst["id"]))
        if not rows:
            return None
        approval_states = {row["name"]: row["approval_state"] for row in rows}
        # Seed the approval cache so a subsequent `tools/call` doesn't re-query.
        self._approval_cache.setdefault(server_url, dict(approval_states))
        return self._format_tool_list(server_url, rows, approval_states)

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
        approval_states = await self._get_approval_states(server_url)
        return self._format_tool_list(server_url, raw_tools, approval_states)

    def _format_tool_list(self, server_url: str, raw_tools: list[dict], approval_states: dict[str, str]) -> str:
        tools: list[MCPToolDefinition] = []
        hidden_do_not_use = 0
        needs_approval_names: list[str] = []
        for raw in raw_tools:
            try:
                tool = MCPToolDefinition.model_validate(raw)
            except ValidationError:
                logger.warning("Skipping malformed tool definition from MCP server", server_url=server_url, raw=raw)
                continue
            state = approval_states.get(tool.name, _APPROVAL_DEFAULT)
            if state == "do_not_use":
                # Invisible to the agent — matches the `do_not_use` semantics in the proxy path.
                hidden_do_not_use += 1
                continue
            if state == "needs_approval":
                needs_approval_names.append(tool.name)
            tools.append(tool)

        if not tools:
            return "This MCP server has no tools available."

        formatted = "\n\n".join(t.format_for_llm() for t in tools)
        notes: list[str] = []
        if needs_approval_names:
            notes.append(
                "The following tools require explicit user approval before each call; the user will be "
                "prompted when you invoke them: " + ", ".join(sorted(needs_approval_names))
            )
        if hidden_do_not_use:
            notes.append(f"{hidden_do_not_use} tool(s) on this server were hidden because the user disabled them.")
        footer = ("\n\n" + "\n".join(notes)) if notes else ""
        return f"Tools available on {server_url}:\n\n{formatted}{footer}"

    async def _call_tool(self, client: MCPClient, server_url: str, tool_name: str, arguments: dict | None) -> str:
        state = await self._resolve_approval_state(server_url, tool_name)
        if state == "do_not_use":
            raise MaxToolFatalError(
                f"Tool '{tool_name}' on {server_url} has been disabled by the user. "
                "It cannot be called. Choose a different tool or explain the limitation."
            )
        # needs_approval is handled earlier via `is_dangerous_operation` + LangGraph
        # interrupt; by the time we reach _call_tool we've already been approved.
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
        inst = self._get_installation(server_url)
        if not is_token_expiring(inst.get("sensitive_configuration") or {}):
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
