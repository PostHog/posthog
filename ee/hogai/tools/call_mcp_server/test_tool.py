import time
import uuid

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import httpx
from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from products.mcp_store.backend.models import MCPServer, MCPServerInstallation
from products.mcp_store.backend.oauth import TokenRefreshError

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tool_errors import MaxToolFatalError, MaxToolRetryableError
from ee.hogai.tools.call_mcp_server.mcp_client import MCPClientError
from ee.hogai.tools.call_mcp_server.tool import CallMCPServerTool, _build_server_headers, _get_installations
from ee.hogai.utils.types.base import AssistantState, NodePath


class TestCallMCPServerTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.state = AssistantState(messages=[])
        self.context_manager = AssistantContextManager(self.team, self.user, {})
        self.node_path = (NodePath(name="test_node", tool_call_id="test_call", message_id="test"),)

    def _install_server(self, name="Test Server", url="https://mcp.example.com/mcp", auth_type="none"):
        server = MCPServer.objects.create(name=name, url=url)
        return MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            server=server,
            display_name=name,
            url=url,
            auth_type=auth_type,
        )

    def _create_tool(self, installations: list[dict] | None = None, conversation_id: str | None = None):
        if installations is None:
            installations = []
        allowed_urls = {inst["url"] for inst in installations}
        server_headers = _build_server_headers(installations)
        description = "test"
        config = RunnableConfig(configurable={"thread_id": conversation_id}) if conversation_id else None
        tool = CallMCPServerTool(
            team=self.team,
            user=self.user,
            state=self.state,
            context_manager=self.context_manager,
            node_path=self.node_path,
            description=description,
            config=config,
        )
        tool._allowed_server_urls = allowed_urls
        tool._installations = installations
        tool._installations_by_url = {inst["url"]: inst for inst in installations}
        tool._server_headers = server_headers
        tool._session_cache = {}
        return tool

    def _make_mock_client(self, session_id: str | None = None):
        mock = AsyncMock()
        mock.initialize = AsyncMock(return_value={})
        mock.list_tools = AsyncMock(return_value=[])
        mock.call_tool = AsyncMock(return_value="ok")
        type(mock).session_id = PropertyMock(return_value=session_id)
        return mock


class TestCreateToolClass(TestCallMCPServerTool):
    async def test_no_installations(self):
        tool = await CallMCPServerTool.create_tool_class(
            team=self.team, user=self.user, state=self.state, context_manager=self.context_manager
        )
        self.assertEqual(tool._installations, [])
        self.assertEqual(tool._allowed_server_urls, set())
        self.assertIn("not available", tool.description.lower())

    async def test_with_installations(self):
        await sync_to_async(self._install_server)(name="Linear", url="https://mcp.linear.app")
        await sync_to_async(self._install_server)(name="Notion", url="https://mcp.notion.so")
        tool = await CallMCPServerTool.create_tool_class(
            team=self.team, user=self.user, state=self.state, context_manager=self.context_manager
        )
        self.assertEqual(len(tool._installations), 2)
        self.assertEqual(tool._allowed_server_urls, {"https://mcp.linear.app", "https://mcp.notion.so"})
        self.assertIn("Linear", tool.description)
        self.assertIn("Notion", tool.description)
        self.assertIn("__list_tools__", tool.description)

    async def test_only_sees_own_installations(self):
        from posthog.models import User

        other_user = await sync_to_async(User.objects.create_and_join)(
            self.organization, "other@example.com", "password"
        )
        server = await sync_to_async(MCPServer.objects.create)(name="Other Server", url="https://mcp.other.com")
        await sync_to_async(MCPServerInstallation.objects.create)(
            team=self.team,
            user=other_user,
            server=server,
            display_name="Other Server",
            url="https://mcp.other.com",
        )

        tool = await CallMCPServerTool.create_tool_class(
            team=self.team, user=self.user, state=self.state, context_manager=self.context_manager
        )
        self.assertEqual(tool._installations, [])


class TestSSRFPrevention(TestCallMCPServerTool):
    async def test_rejects_url_not_in_installations(self):
        tool = self._create_tool(installations=[{"display_name": "Linear", "url": "https://mcp.linear.app"}])
        with self.assertRaises(MaxToolRetryableError) as ctx:
            await tool._arun_impl(server_url="https://evil.com/mcp", tool_name="__list_tools__")
        self.assertIn("not in the user's installed MCP servers", str(ctx.exception))

    async def test_allows_installed_url(self):
        tool = self._create_tool(installations=[{"display_name": "Linear", "url": "https://mcp.linear.app"}])
        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            MockClient.return_value = self._make_mock_client()

            result, artifact = await tool._arun_impl(server_url="https://mcp.linear.app", tool_name="__list_tools__")
            self.assertIn("no tools available", result.lower())


class TestListTools(TestCallMCPServerTool):
    async def test_list_tools_returns_formatted_output(self):
        tool = self._create_tool(installations=[{"display_name": "Linear", "url": "https://mcp.linear.app"}])
        mock_tools = [
            {
                "name": "create_issue",
                "description": "Create a new issue",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Issue title"},
                        "body": {"type": "string", "description": "Issue body"},
                    },
                    "required": ["title"],
                },
            },
        ]

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = self._make_mock_client()
            mock_instance.list_tools = AsyncMock(return_value=mock_tools)
            MockClient.return_value = mock_instance

            result, artifact = await tool._arun_impl(server_url="https://mcp.linear.app", tool_name="__list_tools__")
            self.assertIn("create_issue", result)
            self.assertIn("Create a new issue", result)
            self.assertIn("title", result)
            self.assertIn("(required)", result)
            self.assertIsNone(artifact)

    async def test_list_tools_empty_server(self):
        tool = self._create_tool(installations=[{"display_name": "Empty", "url": "https://mcp.empty.com"}])
        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            MockClient.return_value = self._make_mock_client()

            result, _ = await tool._arun_impl(server_url="https://mcp.empty.com", tool_name="__list_tools__")
            self.assertIn("no tools available", result.lower())


class TestCallTool(TestCallMCPServerTool):
    async def test_call_tool_returns_result(self):
        tool = self._create_tool(installations=[{"display_name": "Linear", "url": "https://mcp.linear.app"}])
        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = self._make_mock_client()
            mock_instance.call_tool = AsyncMock(return_value="Issue LIN-123 created successfully")
            MockClient.return_value = mock_instance

            result, artifact = await tool._arun_impl(
                server_url="https://mcp.linear.app",
                tool_name="create_issue",
                arguments={"title": "Fix bug"},
            )
            self.assertEqual(result, "Issue LIN-123 created successfully")
            self.assertIsNone(artifact)
            mock_instance.call_tool.assert_called_once_with("create_issue", {"title": "Fix bug"})

    async def test_mcp_client_error_becomes_retryable(self):
        tool = self._create_tool(installations=[{"display_name": "Linear", "url": "https://mcp.linear.app"}])
        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = self._make_mock_client()
            mock_instance.initialize = AsyncMock(side_effect=MCPClientError("Connection refused"))
            MockClient.return_value = mock_instance

            with self.assertRaises(MaxToolRetryableError) as ctx:
                await tool._arun_impl(server_url="https://mcp.linear.app", tool_name="create_issue", arguments={})
            self.assertIn("MCP server error", str(ctx.exception))

    async def test_timeout_becomes_retryable(self):
        tool = self._create_tool(installations=[{"display_name": "Slow", "url": "https://mcp.slow.com"}])
        import httpx as _httpx

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = self._make_mock_client()
            mock_instance.initialize = AsyncMock(side_effect=_httpx.TimeoutException("timed out"))
            MockClient.return_value = mock_instance

            with self.assertRaises(MaxToolRetryableError) as ctx:
                await tool._arun_impl(server_url="https://mcp.slow.com", tool_name="some_tool", arguments={})
            self.assertIn("timed out", str(ctx.exception))


class TestSessionCaching(TestCallMCPServerTool):
    SERVER_URL = "https://mcp.linear.app"
    INSTALLATIONS = [{"display_name": "Linear", "url": "https://mcp.linear.app"}]

    async def test_first_call_initializes_and_caches_session(self):
        tool = self._create_tool(installations=self.INSTALLATIONS, conversation_id="conv-1")
        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = self._make_mock_client(session_id="sess-abc")
            MockClient.return_value = mock_instance

            await tool._arun_impl(server_url=self.SERVER_URL, tool_name="__list_tools__")

            mock_instance.initialize.assert_called_once()
            self.assertEqual(tool._session_cache[self.SERVER_URL], "sess-abc")

    async def test_second_call_reuses_session_skips_initialize(self):
        tool = self._create_tool(installations=self.INSTALLATIONS, conversation_id="conv-1")
        tool._session_cache[self.SERVER_URL] = "sess-abc"

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = self._make_mock_client(session_id="sess-abc")
            MockClient.return_value = mock_instance

            await tool._arun_impl(server_url=self.SERVER_URL, tool_name="__list_tools__")

            MockClient.assert_called_once_with(self.SERVER_URL, headers=None, session_id="sess-abc")
            mock_instance.initialize.assert_not_called()

    async def test_stale_session_retries_with_fresh_client(self):
        tool = self._create_tool(installations=self.INSTALLATIONS, conversation_id="conv-1")
        tool._session_cache[self.SERVER_URL] = "stale-sess"

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            stale_client = self._make_mock_client(session_id="stale-sess")
            stale_client.list_tools = AsyncMock(side_effect=MCPClientError("Session expired"))

            fresh_client = self._make_mock_client(session_id="new-sess")
            MockClient.side_effect = [stale_client, fresh_client]

            result, _ = await tool._arun_impl(server_url=self.SERVER_URL, tool_name="__list_tools__")

            self.assertIn("no tools available", result.lower())
            fresh_client.initialize.assert_called_once()
            self.assertEqual(tool._session_cache[self.SERVER_URL], "new-sess")

    async def test_error_without_cached_session_raises_immediately(self):
        tool = self._create_tool(installations=self.INSTALLATIONS, conversation_id="conv-1")

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = self._make_mock_client()
            mock_instance.initialize = AsyncMock(side_effect=MCPClientError("Server down"))
            MockClient.return_value = mock_instance

            with self.assertRaises(MaxToolRetryableError):
                await tool._arun_impl(server_url=self.SERVER_URL, tool_name="__list_tools__")

    async def test_session_persists_in_django_cache(self):
        from django.core.cache import caches

        from ee.hogai.tools.call_mcp_server.tool import _session_cache_key

        tool = self._create_tool(installations=self.INSTALLATIONS, conversation_id="conv-2")

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            MockClient.return_value = self._make_mock_client(session_id="sess-persisted")

            await tool._arun_impl(server_url=self.SERVER_URL, tool_name="__list_tools__")

        key = _session_cache_key("conv-2", self.SERVER_URL)
        self.assertEqual(caches["default"].get(key), "sess-persisted")

    async def test_new_tool_instance_reads_session_from_django_cache(self):
        from django.core.cache import caches

        from ee.hogai.tools.call_mcp_server.tool import _session_cache_key

        key = _session_cache_key("conv-3", self.SERVER_URL)
        caches["default"].set(key, "sess-from-cache", timeout=3600)

        tool = self._create_tool(installations=self.INSTALLATIONS, conversation_id="conv-3")

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            MockClient.return_value = self._make_mock_client(session_id="sess-from-cache")

            await tool._arun_impl(server_url=self.SERVER_URL, tool_name="__list_tools__")

            MockClient.assert_called_once_with(self.SERVER_URL, headers=None, session_id="sess-from-cache")
            MockClient.return_value.initialize.assert_not_called()

    async def test_stale_session_clears_django_cache(self):
        from django.core.cache import caches

        from ee.hogai.tools.call_mcp_server.tool import _session_cache_key

        key = _session_cache_key("conv-4", self.SERVER_URL)
        caches["default"].set(key, "stale-sess", timeout=3600)

        tool = self._create_tool(installations=self.INSTALLATIONS, conversation_id="conv-4")
        tool._session_cache[self.SERVER_URL] = "stale-sess"

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            stale_client = self._make_mock_client(session_id="stale-sess")
            stale_client.list_tools = AsyncMock(side_effect=MCPClientError("Session expired"))

            fresh_client = self._make_mock_client(session_id="new-sess")
            MockClient.side_effect = [stale_client, fresh_client]

            await tool._arun_impl(server_url=self.SERVER_URL, tool_name="__list_tools__")

        self.assertEqual(caches["default"].get(key), "new-sess")

    async def test_no_conversation_id_still_works(self):
        tool = self._create_tool(installations=self.INSTALLATIONS)

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            MockClient.return_value = self._make_mock_client(session_id="sess-no-conv")

            result, _ = await tool._arun_impl(server_url=self.SERVER_URL, tool_name="__list_tools__")
            self.assertIn("no tools available", result.lower())
            MockClient.return_value.initialize.assert_called_once()


class TestGetInstallations(TestCallMCPServerTool):
    def test_returns_installed_servers(self):
        self._install_server(name="Linear", url="https://mcp.linear.app")
        result = _get_installations(self.team, self.user)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["display_name"], "Linear")
        self.assertEqual(result[0]["url"], "https://mcp.linear.app")

    def test_returns_empty_when_none_installed(self):
        result = _get_installations(self.team, self.user)
        self.assertEqual(result, [])


def _make_oauth_installation(
    *,
    server_url: str = "https://mcp.linear.app/mcp",
    server_name: str = "Linear",
    access_token: str = "old-access-token",
    refresh_token: str | None = "old-refresh-token",
    token_retrieved_at: float | str | None = None,
    expires_in: float | str | None = None,
    installation_id: str | None = None,
    oauth_metadata: dict | None = None,
    oauth_client_id: str = "",
) -> dict:
    sensitive: dict = {"access_token": access_token}
    if refresh_token is not None:
        sensitive["refresh_token"] = refresh_token
    if token_retrieved_at is not None:
        sensitive["token_retrieved_at"] = token_retrieved_at
    if expires_in is not None:
        sensitive["expires_in"] = expires_in
    return {
        "id": installation_id or str(uuid.uuid4()),
        "display_name": server_name,
        "url": server_url,
        "auth_type": "oauth",
        "server__oauth_metadata": oauth_metadata or {},
        "server__oauth_client_id": oauth_client_id,
        "configuration": {},
        "sensitive_configuration": sensitive,
    }


class TestIsTokenExpiring(TestCallMCPServerTool):
    SERVER_URL = "https://mcp.linear.app/mcp"

    @parameterized.expand(
        [
            ("fresh_token", time.time(), 3600, False),
            ("past_halfway", time.time() - 2000, 3600, True),
            ("missing_token_retrieved_at", None, 3600, False),
            ("missing_expires_in", time.time(), None, False),
            ("string_numeric_values_fresh", str(time.time()), "3600", False),
            ("string_numeric_values_expired", str(time.time() - 2000), "3600", True),
            ("zero_expires_in", time.time(), 0, False),
        ]
    )
    def test_is_token_expiring(self, _name, token_retrieved_at, expires_in, expected):
        inst = _make_oauth_installation(
            server_url=self.SERVER_URL,
            token_retrieved_at=token_retrieved_at,
            expires_in=expires_in,
        )
        tool = self._create_tool(installations=[inst])
        self.assertEqual(tool._is_token_expiring(self.SERVER_URL), expected)

    def test_unknown_server_returns_false(self):
        tool = self._create_tool(installations=[])
        self.assertFalse(tool._is_token_expiring("https://unknown.example.com"))


class TestSSRFProtection(TestCallMCPServerTool):
    async def test_ssrf_blocked_url_raises_fatal_error(self):
        inst = {
            "id": str(uuid.uuid4()),
            "display_name": "Evil",
            "url": "http://169.254.169.254/latest/meta-data/",
            "auth_type": "none",
            "server__oauth_metadata": {},
            "server__oauth_client_id": "",
            "configuration": {},
            "sensitive_configuration": {},
        }
        tool = self._create_tool(installations=[inst])
        with self.assertRaises(MaxToolFatalError) as ctx:
            await tool._arun_impl("http://169.254.169.254/latest/meta-data/", "__list_tools__")
        self.assertIn("blocked by security policy", str(ctx.exception))


class TestProactiveTokenRefresh(TestCallMCPServerTool):
    SERVER_URL = "https://mcp.linear.app/mcp"

    async def test_refresh_called_when_expiring(self):
        inst = _make_oauth_installation(
            server_url=self.SERVER_URL,
            token_retrieved_at=time.time() - 2000,
            expires_in=3600,
        )
        tool = self._create_tool(installations=[inst])
        tool._refresh_token_for_server = AsyncMock()

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            MockClient.return_value = self._make_mock_client()
            await tool._arun_impl(server_url=self.SERVER_URL, tool_name="__list_tools__")

        tool._refresh_token_for_server.assert_called_once_with(self.SERVER_URL)

    async def test_no_refresh_when_fresh(self):
        inst = _make_oauth_installation(
            server_url=self.SERVER_URL,
            token_retrieved_at=time.time(),
            expires_in=3600,
        )
        tool = self._create_tool(installations=[inst])
        tool._refresh_token_for_server = AsyncMock()

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            MockClient.return_value = self._make_mock_client()
            await tool._arun_impl(server_url=self.SERVER_URL, tool_name="__list_tools__")

        tool._refresh_token_for_server.assert_not_called()

    async def test_proactive_refresh_failure_does_not_block_mcp_call(self):
        inst = _make_oauth_installation(
            server_url=self.SERVER_URL,
            token_retrieved_at=time.time() - 2000,
            expires_in=3600,
        )
        tool = self._create_tool(installations=[inst])
        tool._refresh_token_for_server = AsyncMock(side_effect=TokenRefreshError("refresh failed"))

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            MockClient.return_value = self._make_mock_client()
            result, _ = await tool._arun_impl(server_url=self.SERVER_URL, tool_name="__list_tools__")

        self.assertIn("no tools available", result.lower())


class TestReactive401Refresh(TestCallMCPServerTool):
    SERVER_URL = "https://mcp.linear.app/mcp"

    def _make_401_response(self):
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "Unauthorized"
        resp.headers = {}
        return resp

    async def test_401_triggers_refresh_and_retry(self):
        inst = _make_oauth_installation(server_url=self.SERVER_URL)
        tool = self._create_tool(installations=[inst])
        tool._refresh_token_for_server = AsyncMock()

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            failing_client = self._make_mock_client()
            failing_client.initialize = AsyncMock(
                side_effect=httpx.HTTPStatusError("401", request=MagicMock(), response=self._make_401_response())
            )

            retried_client = self._make_mock_client()
            retried_client.call_tool = AsyncMock(return_value="success after refresh")
            MockClient.side_effect = [failing_client, retried_client]

            result, _ = await tool._arun_impl(
                server_url=self.SERVER_URL, tool_name="some_tool", arguments={"key": "val"}
            )

        tool._refresh_token_for_server.assert_called_once_with(self.SERVER_URL)
        self.assertEqual(result, "success after refresh")

    async def test_401_refresh_failure_raises_fatal(self):
        inst = _make_oauth_installation(server_url=self.SERVER_URL)
        tool = self._create_tool(installations=[inst])
        tool._refresh_token_for_server = AsyncMock(side_effect=TokenRefreshError("bad refresh"))

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            failing_client = self._make_mock_client()
            failing_client.initialize = AsyncMock(
                side_effect=httpx.HTTPStatusError("401", request=MagicMock(), response=self._make_401_response())
            )
            MockClient.return_value = failing_client

            with self.assertRaises(MaxToolFatalError) as ctx:
                await tool._arun_impl(server_url=self.SERVER_URL, tool_name="some_tool")
            self.assertIn("re-authenticate", str(ctx.exception))

    async def test_401_no_refresh_token_raises_fatal(self):
        inst = _make_oauth_installation(server_url=self.SERVER_URL, refresh_token=None)
        tool = self._create_tool(installations=[inst])

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            failing_client = self._make_mock_client()
            failing_client.initialize = AsyncMock(
                side_effect=httpx.HTTPStatusError("401", request=MagicMock(), response=self._make_401_response())
            )
            MockClient.return_value = failing_client

            with self.assertRaises(MaxToolFatalError) as ctx:
                await tool._arun_impl(server_url=self.SERVER_URL, tool_name="some_tool")
            self.assertIn("re-authenticate", str(ctx.exception))

    async def test_non_401_http_error_does_not_trigger_refresh(self):
        inst = _make_oauth_installation(server_url=self.SERVER_URL)
        tool = self._create_tool(installations=[inst])
        tool._refresh_token_for_server = AsyncMock()

        resp_500 = MagicMock()
        resp_500.status_code = 500
        resp_500.text = "Internal Server Error"
        resp_500.headers = {}

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            failing_client = self._make_mock_client()
            failing_client.initialize = AsyncMock(
                side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=resp_500)
            )
            MockClient.return_value = failing_client

            with self.assertRaises(MaxToolRetryableError):
                await tool._arun_impl(server_url=self.SERVER_URL, tool_name="some_tool")

        tool._refresh_token_for_server.assert_not_called()


class TestRefreshTokenPersistence(TestCallMCPServerTool):
    SERVER_URL = "https://mcp.dcr-example.com/mcp"
    OAUTH_METADATA = {"token_endpoint": "https://mcp.dcr-example.com/oauth/token"}
    OAUTH_CLIENT_ID = "dcr-client-123"

    def _install_oauth_server(self, sensitive_config: dict | None = None):
        server = MCPServer.objects.create(
            name="DCR Server",
            url=self.SERVER_URL,
            auth_type="oauth",
            oauth_metadata=self.OAUTH_METADATA,
            oauth_client_id=self.OAUTH_CLIENT_ID,
        )
        return MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            server=server,
            display_name="DCR Server",
            url=self.SERVER_URL,
            auth_type="oauth",
            sensitive_configuration=sensitive_config or {},
        )

    async def test_new_access_token_persisted(self):
        from ee.hogai.tools.call_mcp_server.tool import _refresh_token_sync

        installation_obj = await sync_to_async(self._install_oauth_server)(
            sensitive_config={
                "access_token": "old-token",
                "refresh_token": "my-refresh",
                "expires_in": 3600,
                "token_retrieved_at": int(time.time()) - 2000,
            }
        )

        inst_dict = _make_oauth_installation(
            server_url=self.SERVER_URL,
            installation_id=str(installation_obj.id),
            access_token="old-token",
            refresh_token="my-refresh",
            expires_in=3600,
            token_retrieved_at=int(time.time()) - 2000,
            oauth_metadata=self.OAUTH_METADATA,
            oauth_client_id=self.OAUTH_CLIENT_ID,
        )

        with patch("products.mcp_store.backend.oauth.refresh_oauth_token") as mock_refresh:
            mock_refresh.return_value = {
                "access_token": "new-access-token",
                "expires_in": 3600,
            }
            result = await sync_to_async(_refresh_token_sync)(inst_dict)

        self.assertEqual(result["access_token"], "new-access-token")
        self.assertEqual(result["refresh_token"], "my-refresh")
        self.assertIn("token_retrieved_at", result)

        updated = await sync_to_async(MCPServerInstallation.objects.get)(id=installation_obj.id)
        self.assertEqual(updated.sensitive_configuration["access_token"], "new-access-token")

    async def test_rotated_refresh_token_saved(self):
        from ee.hogai.tools.call_mcp_server.tool import _refresh_token_sync

        installation_obj = await sync_to_async(self._install_oauth_server)(
            sensitive_config={
                "access_token": "old-token",
                "refresh_token": "old-refresh",
                "expires_in": 3600,
                "token_retrieved_at": int(time.time()) - 2000,
            }
        )

        inst_dict = _make_oauth_installation(
            server_url=self.SERVER_URL,
            installation_id=str(installation_obj.id),
            access_token="old-token",
            refresh_token="old-refresh",
            expires_in=3600,
            token_retrieved_at=int(time.time()) - 2000,
            oauth_metadata=self.OAUTH_METADATA,
            oauth_client_id=self.OAUTH_CLIENT_ID,
        )

        with patch("products.mcp_store.backend.oauth.refresh_oauth_token") as mock_refresh:
            mock_refresh.return_value = {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 7200,
            }
            result = await sync_to_async(_refresh_token_sync)(inst_dict)

        self.assertEqual(result["refresh_token"], "new-refresh")
        self.assertEqual(result["expires_in"], 7200)

        updated = await sync_to_async(MCPServerInstallation.objects.get)(id=installation_obj.id)
        self.assertEqual(updated.sensitive_configuration["refresh_token"], "new-refresh")

    async def test_original_refresh_token_preserved_when_not_rotated(self):
        from ee.hogai.tools.call_mcp_server.tool import _refresh_token_sync

        installation_obj = await sync_to_async(self._install_oauth_server)(
            sensitive_config={
                "access_token": "old-token",
                "refresh_token": "original-refresh",
                "expires_in": 3600,
                "token_retrieved_at": int(time.time()) - 2000,
            }
        )

        inst_dict = _make_oauth_installation(
            server_url=self.SERVER_URL,
            installation_id=str(installation_obj.id),
            access_token="old-token",
            refresh_token="original-refresh",
            expires_in=3600,
            token_retrieved_at=int(time.time()) - 2000,
            oauth_metadata=self.OAUTH_METADATA,
            oauth_client_id=self.OAUTH_CLIENT_ID,
        )

        with patch("products.mcp_store.backend.oauth.refresh_oauth_token") as mock_refresh:
            mock_refresh.return_value = {
                "access_token": "new-access",
            }
            result = await sync_to_async(_refresh_token_sync)(inst_dict)

        self.assertEqual(result["refresh_token"], "original-refresh")

        updated = await sync_to_async(MCPServerInstallation.objects.get)(id=installation_obj.id)
        self.assertEqual(updated.sensitive_configuration["refresh_token"], "original-refresh")
