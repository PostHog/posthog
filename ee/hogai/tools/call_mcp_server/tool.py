import time
from typing import Literal, Self

from django.core.cache import caches

import httpx
import structlog
from pydantic import BaseModel, Field

from posthog.schema import AssistantTool

from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolFatalError, MaxToolRetryableError
from ee.hogai.utils.types.base import AssistantState, NodePath

from .mcp_client import MCPClient, MCPClientError

logger = structlog.get_logger(__name__)

SESSION_CACHE_TTL = 3600  # 1 hour


def _session_cache_key(conversation_id: str, server_url: str) -> str:
    return f"mcp_session:{conversation_id}:{server_url}"


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
            server_lines = "\n".join(f"- {inst['server__name']}: {inst['server__url']}" for inst in installations)
            description = (
                "Call a tool on a user-installed MCP server. "
                "The user has the following MCP servers installed:\n"
                f"{server_lines}\n\n"
                "To discover what tools a server offers, call this with tool_name='__list_tools__' "
                "and the server_url. Then use the returned tool definitions to make actual tool calls."
            )

        allowed_urls = {inst["server__url"] for inst in installations}
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
        instance._installations_by_url = {inst["server__url"]: inst for inst in installations}
        instance._server_headers = server_headers
        instance._session_cache: dict[str, str] = {}
        return instance

    def _is_token_expiring(self, server_url: str) -> bool:
        inst = self._installations_by_url.get(server_url)
        if not inst:
            return False
        sensitive = inst.get("sensitive_configuration") or {}
        try:
            token_retrieved_at = float(sensitive.get("token_retrieved_at", 0))
            expires_in = float(sensitive.get("expires_in", 0))
        except (TypeError, ValueError):
            return False
        if not token_retrieved_at or not expires_in:
            return False
        return time.time() > token_retrieved_at + (expires_in / 2)

    async def _refresh_token_for_server(self, server_url: str) -> None:
        inst = self._installations_by_url.get(server_url)
        if not inst:
            raise MaxToolFatalError(f"No installation found for {server_url}")

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

    async def _mark_needs_reauth(self, server_url: str) -> None:
        inst = self._installations_by_url.get(server_url)
        if not inst:
            return
        await database_sync_to_async(_mark_needs_reauth_sync)(inst["id"])

    async def _arun_impl(self, server_url: str, tool_name: str, arguments: dict | None = None) -> tuple[str, None]:
        if server_url not in self._allowed_server_urls:
            raise MaxToolRetryableError(
                f"Server URL '{server_url}' is not in the user's installed MCP servers. "
                f"Allowed URLs: {', '.join(sorted(self._allowed_server_urls))}"
            )

        if self._is_token_expiring(server_url):
            try:
                await self._refresh_token_for_server(server_url)
                self._clear_cached_session(server_url)
            except Exception:
                logger.warning("Proactive token refresh failed, continuing with current token", server_url=server_url)

        headers = self._server_headers.get(server_url)
        session_id = self._get_cached_session(server_url)
        client = MCPClient(server_url, headers=headers, session_id=session_id)

        try:
            try:
                if not session_id:
                    await client.initialize()
                result = await self._execute_mcp_call(client, server_url, tool_name, arguments)
                self._cache_session(server_url, client.session_id)
                return result, None
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    await client.close()
                    return await self._handle_401_refresh(server_url, tool_name, arguments), None
                if session_id:
                    self._clear_cached_session(server_url)
                    await client.close()
                    client = MCPClient(server_url, headers=headers)
                    await client.initialize()
                    result = await self._execute_mcp_call(client, server_url, tool_name, arguments)
                    self._cache_session(server_url, client.session_id)
                    return result, None
                raise
            except MCPClientError:
                if session_id:
                    self._clear_cached_session(server_url)
                    await client.close()
                    client = MCPClient(server_url, headers=headers)
                    await client.initialize()
                    result = await self._execute_mcp_call(client, server_url, tool_name, arguments)
                    self._cache_session(server_url, client.session_id)
                    return result, None
                raise
        except MCPClientError as e:
            raise MaxToolRetryableError(f"MCP server error: {e}")
        except httpx.HTTPStatusError as e:
            raise MaxToolRetryableError(f"MCP server returned HTTP {e.response.status_code}: {e.response.text[:500]}")
        except httpx.TimeoutException:
            raise MaxToolRetryableError(f"MCP server at {server_url} timed out. The server may be unavailable.")
        except httpx.ConnectError:
            raise MaxToolRetryableError(f"Could not connect to MCP server at {server_url}. The server may be down.")
        finally:
            await client.close()

    async def _handle_401_refresh(self, server_url: str, tool_name: str, arguments: dict | None) -> str:
        from products.mcp_store.backend.oauth import TokenRefreshError

        try:
            await self._refresh_token_for_server(server_url)
        except (TokenRefreshError, MaxToolFatalError) as e:
            await self._mark_needs_reauth(server_url)
            raise MaxToolFatalError(
                f"Authentication failed for {server_url} and token refresh failed: {e}. "
                "Ask the user to re-authenticate with this MCP server in the MCP store settings page."
            )

        self._clear_cached_session(server_url)
        headers = self._server_headers.get(server_url)
        client = MCPClient(server_url, headers=headers)
        try:
            await client.initialize()
            result = await self._execute_mcp_call(client, server_url, tool_name, arguments)
            self._cache_session(server_url, client.session_id)
            return result
        finally:
            await client.close()

    async def _execute_mcp_call(
        self, client: MCPClient, server_url: str, tool_name: str, arguments: dict | None
    ) -> str:
        if tool_name == "__list_tools__":
            tools = await client.list_tools()
            if not tools:
                return "This MCP server has no tools available."

            lines = []
            for tool in tools:
                name = tool.get("name", "unknown")
                desc = tool.get("description", "No description")
                schema = tool.get("inputSchema", {})
                props = schema.get("properties", {})
                required = schema.get("required", [])

                param_parts = []
                for param_name, param_info in props.items():
                    param_type = param_info.get("type", "any")
                    param_desc = param_info.get("description", "")
                    req = " (required)" if param_name in required else ""
                    param_parts.append(f"    - {param_name}: {param_type}{req} — {param_desc}")

                params_str = "\n".join(param_parts) if param_parts else "    (no parameters)"
                lines.append(f"- **{name}**: {desc}\n  Parameters:\n{params_str}")

            return f"Tools available on {server_url}:\n\n" + "\n\n".join(lines)

        return await client.call_tool(tool_name, arguments or {})

    def _get_cached_session(self, server_url: str) -> str | None:
        if sid := self._session_cache.get(server_url):
            return sid
        conversation_id = self._get_conversation_id()
        if not conversation_id:
            return None
        key = _session_cache_key(conversation_id, server_url)
        sid = caches["default"].get(key)
        if sid:
            self._session_cache[server_url] = sid
        return sid

    def _cache_session(self, server_url: str, session_id: str | None) -> None:
        if not session_id:
            return
        self._session_cache[server_url] = session_id
        conversation_id = self._get_conversation_id()
        if not conversation_id:
            return
        key = _session_cache_key(conversation_id, server_url)
        caches["default"].set(key, session_id, timeout=SESSION_CACHE_TTL)

    def _clear_cached_session(self, server_url: str) -> None:
        self._session_cache.pop(server_url, None)
        conversation_id = self._get_conversation_id()
        if not conversation_id:
            return
        key = _session_cache_key(conversation_id, server_url)
        caches["default"].delete(key)


def _get_installations(team: Team, user: User) -> list[dict]:
    from products.mcp_store.backend.models import MCPServerInstallation

    return list(
        MCPServerInstallation.objects.filter(team=team, user=user)
        .select_related("server")
        .values(
            "id",
            "server__name",
            "server__url",
            "server__auth_type",
            "server__oauth_metadata",
            "server__oauth_client_id",
            "configuration",
            "sensitive_configuration",
        )
    )


def _mark_needs_reauth_sync(installation_id: str) -> None:
    from products.mcp_store.backend.models import MCPServerInstallation

    try:
        inst = MCPServerInstallation.objects.get(id=installation_id)
    except MCPServerInstallation.DoesNotExist:
        return
    sensitive = inst.sensitive_configuration or {}
    sensitive["needs_reauth"] = True
    inst.sensitive_configuration = sensitive
    inst.save(update_fields=["sensitive_configuration", "updated_at"])


def _refresh_token_sync(installation: dict) -> dict:
    import time as _time

    from posthog.models.integration import OauthIntegration

    from products.mcp_store.backend.models import OAUTH_KIND_MAP, MCPServerInstallation
    from products.mcp_store.backend.oauth import TokenRefreshError, refresh_oauth_token

    sensitive = installation.get("sensitive_configuration") or {}
    refresh_token = sensitive.get("refresh_token")
    if not refresh_token:
        raise TokenRefreshError("No refresh token available")

    server_url = installation["server__url"]
    kind = OAUTH_KIND_MAP.get(server_url)

    if kind:
        try:
            oauth_config = OauthIntegration.oauth_config_for_kind(kind)
            token_url = oauth_config.token_url
            client_id = oauth_config.client_id
            client_secret = oauth_config.client_secret
        except NotImplementedError:
            kind = None

    if not kind:
        metadata = installation.get("server__oauth_metadata") or {}
        token_url = metadata.get("token_endpoint", "")
        client_id = installation.get("server__oauth_client_id", "")
        client_secret = None
        if not token_url or not client_id:
            raise TokenRefreshError("Missing OAuth metadata for token refresh")

    token_data = refresh_oauth_token(
        token_url=token_url,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
    )

    updated_sensitive: dict = {
        "access_token": token_data["access_token"],
        "token_retrieved_at": int(_time.time()),
        "refresh_token": token_data.get("refresh_token", refresh_token),
    }
    if "expires_in" in token_data:
        updated_sensitive["expires_in"] = token_data["expires_in"]
    elif "expires_in" in sensitive:
        updated_sensitive["expires_in"] = sensitive["expires_in"]

    inst_obj = MCPServerInstallation.objects.get(id=installation["id"])
    inst_obj.sensitive_configuration = updated_sensitive
    inst_obj.save(update_fields=["sensitive_configuration", "updated_at"])

    return updated_sensitive


def _build_server_headers(installations: list[dict]) -> dict[str, dict[str, str]]:
    """Build auth headers for each server URL from installation configuration."""
    headers: dict[str, dict[str, str]] = {}
    for inst in installations:
        url = inst["server__url"]
        auth_type = inst.get("server__auth_type", "none")
        sensitive = inst.get("sensitive_configuration") or {}

        if auth_type == "api_key":
            api_key = sensitive.get("api_key")
            if not api_key:
                # Fallback for pre-migration installations
                config = inst.get("configuration") or {}
                api_key = config.get("api_key")
            if api_key:
                headers[url] = {"Authorization": f"Bearer {api_key}"}
        elif auth_type == "oauth":
            if access_token := sensitive.get("access_token"):
                headers[url] = {"Authorization": f"Bearer {access_token}"}

    return headers
