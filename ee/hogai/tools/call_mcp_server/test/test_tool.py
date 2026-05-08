import time
import uuid

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from products.mcp_store.backend.models import MCPServerInstallation, MCPServerInstallationTool
from products.mcp_store.backend.oauth import TokenRefreshError

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tool_errors import MaxToolFatalError, MaxToolRetryableError
from ee.hogai.tools.call_mcp_server.installations import _build_server_headers, _get_installations
from ee.hogai.tools.call_mcp_server.mcp_client import MCPClientError
from ee.hogai.tools.call_mcp_server.tool import CallMCPServerTool
from ee.hogai.utils.types.base import AssistantState, NodePath


class TestCallMCPServerTool(BaseTest):
    def setUp(self):
        super().setUp()
        self.state = AssistantState(messages=[])
        self.context_manager = AssistantContextManager(self.team, self.user, {})
        self.node_path = (NodePath(name="test_node", tool_call_id="test_call", message_id="test"),)
        # Bypass SSRF DNS resolution for fake test domains
        patcher = patch("ee.hogai.tools.call_mcp_server.tool.is_url_allowed", return_value=(True, None))
        self.mock_is_url_allowed = patcher.start()
        self.addCleanup(patcher.stop)

    def _install_server(
        self,
        name="Test Server",
        url="https://mcp.example.com/mcp",
        auth_type="api_key",
        sensitive_configuration=None,
    ):
        return MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name=name,
            url=url,
            auth_type=auth_type,
            sensitive_configuration=sensitive_configuration or {},
        )

    def _create_tool(self, installations: list[dict] | None = None, conversation_id: str | None = None):
        if installations is None:
            installations = []
        for inst in installations:
            inst.setdefault("id", str(uuid.uuid4()))
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
        tool._approval_cache = {}
        return tool

    def _make_mock_client(self):
        mock = AsyncMock()
        mock.initialize = AsyncMock(return_value=None)
        mock.list_tools = AsyncMock(return_value=[])
        mock.call_tool = AsyncMock(return_value="ok")
        mock.close = AsyncMock()
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
        await sync_to_async(MCPServerInstallation.objects.create)(
            team=self.team,
            user=other_user,
            display_name="Other Server",
            url="https://mcp.other.com",
        )

        tool = await CallMCPServerTool.create_tool_class(
            team=self.team, user=self.user, state=self.state, context_manager=self.context_manager
        )
        self.assertEqual(tool._installations, [])


class TestAuthHeaders(TestCallMCPServerTool):
    async def test_oauth_token_sent_as_bearer_header(self):
        inst = _make_oauth_installation(
            server_url="https://mcp.linear.app/mcp",
            access_token="my-oauth-token",
        )
        tool = self._create_tool(installations=[inst])

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            MockClient.return_value = self._make_mock_client()
            await tool._arun_impl(server_url="https://mcp.linear.app/mcp", tool_name="__list_tools__")

            MockClient.assert_called_once()
            _, kwargs = MockClient.call_args
            self.assertEqual(kwargs["headers"], {"Authorization": "Bearer my-oauth-token"})

    async def test_api_key_sent_as_bearer_header(self):
        inst = {
            "id": str(uuid.uuid4()),
            "display_name": "Server",
            "url": "https://mcp.example.com",
            "auth_type": "api_key",
            "server__oauth_metadata": {},
            "server__oauth_client_id": "",
            "sensitive_configuration": {"api_key": "my-api-key"},
        }
        tool = self._create_tool(installations=[inst])

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            MockClient.return_value = self._make_mock_client()
            await tool._arun_impl(server_url="https://mcp.example.com", tool_name="__list_tools__")

            _, kwargs = MockClient.call_args
            self.assertEqual(kwargs["headers"], {"Authorization": "Bearer my-api-key"})

    async def test_no_auth_sends_no_headers(self):
        inst = {
            "id": str(uuid.uuid4()),
            "display_name": "Server",
            "url": "https://mcp.example.com",
            "auth_type": "api_key",
            "server__oauth_metadata": {},
            "server__oauth_client_id": "",
            "sensitive_configuration": {},
        }
        tool = self._create_tool(installations=[inst])

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            MockClient.return_value = self._make_mock_client()
            await tool._arun_impl(server_url="https://mcp.example.com", tool_name="__list_tools__")

            _, kwargs = MockClient.call_args
            self.assertIsNone(kwargs["headers"])


class TestSSRFPrevention(TestCallMCPServerTool):
    async def test_rejects_url_not_in_installations(self):
        tool = self._create_tool(installations=[{"display_name": "Linear", "url": "https://mcp.linear.app"}])
        with self.assertRaises(MaxToolFatalError) as ctx:
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
        tool._refresh_auth_or_mark_reauth = AsyncMock()
        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = self._make_mock_client()
            mock_instance.initialize = AsyncMock(side_effect=MCPClientError("Connection refused"))
            MockClient.return_value = mock_instance

            with self.assertRaises(MaxToolRetryableError) as ctx:
                await tool._arun_impl(server_url="https://mcp.linear.app", tool_name="create_issue", arguments={})
            self.assertIn("MCP server error", str(ctx.exception))

    async def test_timeout_error_becomes_retryable(self):
        tool = self._create_tool(installations=[{"display_name": "Slow", "url": "https://mcp.slow.com"}])
        tool._refresh_auth_or_mark_reauth = AsyncMock()

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = self._make_mock_client()
            mock_instance.initialize = AsyncMock(side_effect=MCPClientError("timed out"))
            MockClient.return_value = mock_instance

            with self.assertRaises(MaxToolRetryableError) as ctx:
                await tool._arun_impl(server_url="https://mcp.slow.com", tool_name="some_tool", arguments={})
            self.assertIn("timed out", str(ctx.exception))

    async def test_connect_error_becomes_retryable(self):
        tool = self._create_tool(installations=[{"display_name": "Down", "url": "https://mcp.down.com"}])
        tool._refresh_auth_or_mark_reauth = AsyncMock()

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = self._make_mock_client()
            mock_instance.initialize = AsyncMock(side_effect=MCPClientError("Failed to connect to MCP server"))
            MockClient.return_value = mock_instance

            with self.assertRaises(MaxToolRetryableError) as ctx:
                await tool._arun_impl(server_url="https://mcp.down.com", tool_name="some_tool", arguments={})
            self.assertIn("Failed to connect", str(ctx.exception))


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
        "sensitive_configuration": sensitive,
    }


class TestIsTokenExpiring(TestCallMCPServerTool):
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
        from products.mcp_store.backend.oauth import is_token_expiring

        sensitive: dict = {"access_token": "tok", "refresh_token": "rt"}
        if token_retrieved_at is not None:
            sensitive["token_retrieved_at"] = token_retrieved_at
        if expires_in is not None:
            sensitive["expires_in"] = expires_in
        self.assertEqual(is_token_expiring(sensitive), expected)


class TestSSRFProtection(TestCallMCPServerTool):
    async def test_ssrf_blocked_url_raises_fatal_error(self):
        self.mock_is_url_allowed.return_value = (False, "Local/metadata host")
        inst = {
            "id": str(uuid.uuid4()),
            "display_name": "Evil",
            "url": "http://169.254.169.254/latest/meta-data/",
            "auth_type": "api_key",
            "server__oauth_metadata": {},
            "server__oauth_client_id": "",
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


class TestAuthRefresh(TestCallMCPServerTool):
    SERVER_URL = "https://mcp.linear.app/mcp"

    async def test_error_on_authed_server_triggers_refresh_and_retry(self):
        inst = _make_oauth_installation(server_url=self.SERVER_URL)
        tool = self._create_tool(installations=[inst])
        tool._refresh_token_for_server = AsyncMock()

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            failing_client = self._make_mock_client()
            failing_client.initialize = AsyncMock(side_effect=MCPClientError("auth error"))

            retried_client = self._make_mock_client()
            retried_client.call_tool = AsyncMock(return_value="success after refresh")
            MockClient.side_effect = [failing_client, retried_client]

            result, _ = await tool._arun_impl(
                server_url=self.SERVER_URL, tool_name="some_tool", arguments={"key": "val"}
            )

        tool._refresh_token_for_server.assert_called_once_with(self.SERVER_URL)
        self.assertEqual(result, "success after refresh")

    async def test_refresh_failure_raises_fatal(self):
        inst = _make_oauth_installation(server_url=self.SERVER_URL)
        tool = self._create_tool(installations=[inst])
        tool._refresh_token_for_server = AsyncMock(side_effect=TokenRefreshError("bad refresh"))

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            failing_client = self._make_mock_client()
            failing_client.initialize = AsyncMock(side_effect=MCPClientError("auth error"))
            MockClient.return_value = failing_client

            with self.assertRaises(MaxToolFatalError) as ctx:
                await tool._arun_impl(server_url=self.SERVER_URL, tool_name="some_tool")
            self.assertIn("re-authenticate", str(ctx.exception))

    async def test_refresh_failure_marks_installation_for_reauth(self):
        installation = await sync_to_async(self._install_server)(
            name="OAuth Server", url=self.SERVER_URL, auth_type="oauth"
        )
        inst = _make_oauth_installation(server_url=self.SERVER_URL, installation_id=str(installation.id))
        tool = self._create_tool(installations=[inst])
        tool._refresh_token_for_server = AsyncMock(side_effect=TokenRefreshError("bad refresh"))

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            failing_client = self._make_mock_client()
            failing_client.initialize = AsyncMock(side_effect=MCPClientError("auth error"))
            MockClient.return_value = failing_client

            with self.assertRaises(MaxToolFatalError):
                await tool._arun_impl(server_url=self.SERVER_URL, tool_name="some_tool")

        await sync_to_async(installation.refresh_from_db)()
        self.assertTrue(installation.sensitive_configuration.get("needs_reauth"))

    async def test_no_refresh_token_raises_fatal(self):
        inst = _make_oauth_installation(server_url=self.SERVER_URL, refresh_token=None)
        tool = self._create_tool(installations=[inst])

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            failing_client = self._make_mock_client()
            failing_client.initialize = AsyncMock(side_effect=MCPClientError("auth error"))
            MockClient.return_value = failing_client

            with self.assertRaises(MaxToolFatalError) as ctx:
                await tool._arun_impl(server_url=self.SERVER_URL, tool_name="some_tool")
            self.assertIn("re-authenticate", str(ctx.exception))


class TestRefreshTokenFromMetadata(TestCallMCPServerTool):
    SERVER_URL = "https://mcp.linear.app/mcp"

    async def test_refresh_uses_server_metadata(self):
        sensitive_config = {
            "access_token": "old-token",
            "refresh_token": "rt",
            "token_retrieved_at": int(time.time() - 2000),
            "expires_in": 3600,
            "dcr_client_id": "linear-client",
        }
        installation = await sync_to_async(self._install_server)(
            name="Linear",
            url=self.SERVER_URL,
            auth_type="oauth",
            sensitive_configuration=sensitive_config,
        )
        installation.oauth_metadata = {"token_endpoint": "https://linear.app/oauth/token"}
        await sync_to_async(installation.save)(update_fields=["oauth_metadata"])
        inst = _make_oauth_installation(
            server_url=self.SERVER_URL,
            installation_id=str(installation.id),
            token_retrieved_at=time.time() - 2000,
            expires_in=3600,
            oauth_metadata={"token_endpoint": "https://linear.app/oauth/token"},
            oauth_client_id="linear-client",
        )
        tool = self._create_tool(installations=[inst])

        with (
            patch("products.mcp_store.backend.oauth.refresh_oauth_token") as mock_refresh,
            patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient,
        ):
            mock_refresh.return_value = {"access_token": "new-token", "expires_in": 3600}
            MockClient.return_value = self._make_mock_client()

            result, _ = await tool._arun_impl(server_url=self.SERVER_URL, tool_name="__list_tools__")

        self.assertIn("no tools available", result.lower())
        await sync_to_async(installation.refresh_from_db)()
        self.assertEqual(installation.sensitive_configuration["access_token"], "new-token")


class TestRefreshTokenPersistence(TestCallMCPServerTool):
    SERVER_URL = "https://mcp.dcr-example.com/mcp"
    OAUTH_METADATA = {"token_endpoint": "https://mcp.dcr-example.com/oauth/token"}
    OAUTH_CLIENT_ID = "dcr-client-123"

    def _install_oauth_server(self, sensitive_config: dict | None = None):
        sensitive = dict(sensitive_config or {})
        sensitive.setdefault("dcr_client_id", self.OAUTH_CLIENT_ID)
        return MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            display_name="DCR Server",
            url=self.SERVER_URL,
            auth_type="oauth",
            oauth_metadata=self.OAUTH_METADATA,
            sensitive_configuration=sensitive,
        )

    async def test_new_access_token_persisted(self):
        from ee.hogai.tools.call_mcp_server.installations import _refresh_token_sync

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
        from ee.hogai.tools.call_mcp_server.installations import _refresh_token_sync

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
        from ee.hogai.tools.call_mcp_server.installations import _refresh_token_sync

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


class TestToolApprovalEnforcement(TestCallMCPServerTool):
    """Covers the per-tool approval_state gate inside the Max agent's call path.

    Mirrors the enforcement the HTTP /proxy/ endpoint does, but reached via the
    LangGraph agent (CallMCPServerTool) which does not go through /proxy/."""

    SERVER_URL = "https://mcp.linear.app/mcp"

    def _seed_installation_and_tools(self, tool_states: dict[str, str]) -> MCPServerInstallation:
        installation = self._install_server(
            name="Linear", url=self.SERVER_URL, auth_type="api_key", sensitive_configuration={"api_key": "k"}
        )
        now = timezone.now()
        for tool_name, approval_state in tool_states.items():
            MCPServerInstallationTool.objects.create(
                installation=installation,
                tool_name=tool_name,
                approval_state=approval_state,
                last_seen_at=now,
            )
        return installation

    def _make_inst_dict(self, installation: MCPServerInstallation) -> dict:
        return {
            "id": str(installation.id),
            "display_name": installation.display_name,
            "url": installation.url,
            "auth_type": installation.auth_type,
            "sensitive_configuration": installation.sensitive_configuration,
        }

    async def test_list_tools_filters_do_not_use(self):
        installation = await sync_to_async(self._seed_installation_and_tools)(
            {"create_issue": "approved", "delete_everything": "do_not_use"}
        )
        tool = self._create_tool(installations=[self._make_inst_dict(installation)])

        raw_tools = [
            {"name": "create_issue", "description": "Create", "inputSchema": {}},
            {"name": "delete_everything", "description": "Danger", "inputSchema": {}},
        ]
        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = self._make_mock_client()
            mock_instance.list_tools = AsyncMock(return_value=raw_tools)
            MockClient.return_value = mock_instance

            result, _ = await tool._arun_impl(server_url=self.SERVER_URL, tool_name="__list_tools__")

        self.assertIn("create_issue", result)
        self.assertNotIn("delete_everything", result)
        self.assertIn("hidden because the user disabled them", result)

    async def test_list_tools_annotates_needs_approval(self):
        installation = await sync_to_async(self._seed_installation_and_tools)(
            {"create_issue": "approved", "rename_org": "needs_approval"}
        )
        tool = self._create_tool(installations=[self._make_inst_dict(installation)])

        raw_tools = [
            {"name": "create_issue", "description": "Create", "inputSchema": {}},
            {"name": "rename_org", "description": "Rename", "inputSchema": {}},
        ]
        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = self._make_mock_client()
            mock_instance.list_tools = AsyncMock(return_value=raw_tools)
            MockClient.return_value = mock_instance

            result, _ = await tool._arun_impl(server_url=self.SERVER_URL, tool_name="__list_tools__")

        self.assertIn("rename_org", result)
        self.assertIn("require explicit user approval", result)

    async def test_list_tools_treats_unknown_as_needs_approval(self):
        installation = await sync_to_async(self._seed_installation_and_tools)({})
        tool = self._create_tool(installations=[self._make_inst_dict(installation)])

        raw_tools = [{"name": "brand_new_tool", "description": "New", "inputSchema": {}}]
        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = self._make_mock_client()
            mock_instance.list_tools = AsyncMock(return_value=raw_tools)
            MockClient.return_value = mock_instance

            result, _ = await tool._arun_impl(server_url=self.SERVER_URL, tool_name="__list_tools__")

        self.assertIn("brand_new_tool", result)
        self.assertIn("require explicit user approval", result)

    async def test_call_tool_with_do_not_use_raises_fatal(self):
        installation = await sync_to_async(self._seed_installation_and_tools)({"delete_everything": "do_not_use"})
        tool = self._create_tool(installations=[self._make_inst_dict(installation)])

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            MockClient.return_value = self._make_mock_client()
            with self.assertRaises(MaxToolFatalError) as ctx:
                await tool._arun_impl(server_url=self.SERVER_URL, tool_name="delete_everything", arguments={})

        self.assertIn("disabled by the user", str(ctx.exception))

    async def test_call_tool_with_approved_state_passes_through(self):
        installation = await sync_to_async(self._seed_installation_and_tools)({"create_issue": "approved"})
        tool = self._create_tool(installations=[self._make_inst_dict(installation)])

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = self._make_mock_client()
            mock_instance.call_tool = AsyncMock(return_value="ok")
            MockClient.return_value = mock_instance

            result, _ = await tool._arun_impl(
                server_url=self.SERVER_URL, tool_name="create_issue", arguments={"title": "x"}
            )

        self.assertEqual(result, "ok")
        mock_instance.call_tool.assert_called_once_with("create_issue", {"title": "x"})

    async def test_removed_tool_treated_as_do_not_use(self):
        # Tool that vanished upstream should be uncallable even if its saved
        # approval_state is "approved" — removed_at wins.
        installation = await sync_to_async(self._install_server)(
            name="Linear", url=self.SERVER_URL, auth_type="api_key"
        )
        now = timezone.now()
        await sync_to_async(MCPServerInstallationTool.objects.create)(
            installation=installation,
            tool_name="create_issue",
            approval_state="approved",
            last_seen_at=now,
            removed_at=now,
        )
        tool = self._create_tool(installations=[self._make_inst_dict(installation)])

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            MockClient.return_value = self._make_mock_client()
            with self.assertRaises(MaxToolFatalError):
                await tool._arun_impl(server_url=self.SERVER_URL, tool_name="create_issue", arguments={})


class TestIsDangerousOperation(TestCallMCPServerTool):
    """Covers the LangGraph interrupt trigger for needs_approval tools."""

    SERVER_URL = "https://mcp.linear.app/mcp"

    def _seed(self, tool_states: dict[str, str]) -> MCPServerInstallation:
        installation = self._install_server(
            name="Linear", url=self.SERVER_URL, auth_type="api_key", sensitive_configuration={"api_key": "k"}
        )
        now = timezone.now()
        for tool_name, approval_state in tool_states.items():
            MCPServerInstallationTool.objects.create(
                installation=installation,
                tool_name=tool_name,
                approval_state=approval_state,
                last_seen_at=now,
            )
        return installation

    def _inst_dict(self, installation: MCPServerInstallation) -> dict:
        return {
            "id": str(installation.id),
            "display_name": installation.display_name,
            "url": installation.url,
            "auth_type": installation.auth_type,
            "sensitive_configuration": installation.sensitive_configuration,
        }

    async def test_list_tools_never_triggers_approval(self):
        installation = await sync_to_async(self._seed)({})
        tool = self._create_tool(installations=[self._inst_dict(installation)])
        self.assertFalse(await tool.is_dangerous_operation(server_url=self.SERVER_URL, tool_name="__list_tools__"))

    async def test_needs_approval_triggers_approval(self):
        installation = await sync_to_async(self._seed)({"rename_org": "needs_approval"})
        tool = self._create_tool(installations=[self._inst_dict(installation)])
        self.assertTrue(await tool.is_dangerous_operation(server_url=self.SERVER_URL, tool_name="rename_org"))

    async def test_approved_does_not_trigger_approval(self):
        installation = await sync_to_async(self._seed)({"create_issue": "approved"})
        tool = self._create_tool(installations=[self._inst_dict(installation)])
        self.assertFalse(await tool.is_dangerous_operation(server_url=self.SERVER_URL, tool_name="create_issue"))

    async def test_unknown_tool_defaults_to_needs_approval(self):
        installation = await sync_to_async(self._seed)({})
        tool = self._create_tool(installations=[self._inst_dict(installation)])
        self.assertTrue(await tool.is_dangerous_operation(server_url=self.SERVER_URL, tool_name="new_tool"))

    async def test_unknown_server_url_does_not_trigger_approval(self):
        # Validation will reject it during execution; approval gate stays off.
        installation = await sync_to_async(self._seed)({})
        tool = self._create_tool(installations=[self._inst_dict(installation)])
        self.assertFalse(
            await tool.is_dangerous_operation(server_url="https://mcp.not-installed.com", tool_name="anything")
        )

    async def test_list_tools_uses_cache_when_available(self):
        def setup():
            installation = self._install_server(
                name="Linear", url=self.SERVER_URL, auth_type="api_key", sensitive_configuration={"api_key": "k"}
            )
            now = timezone.now()
            MCPServerInstallationTool.objects.create(
                installation=installation,
                tool_name="create_issue",
                description="Create an issue",
                input_schema={
                    "type": "object",
                    "properties": {"title": {"type": "string", "description": "Issue title"}},
                    "required": ["title"],
                },
                approval_state="approved",
                last_seen_at=now,
            )
            MCPServerInstallationTool.objects.create(
                installation=installation,
                tool_name="delete_everything",
                approval_state="do_not_use",
                last_seen_at=now,
            )
            return installation

        installation = await sync_to_async(setup)()
        tool = self._create_tool(installations=[self._inst_dict(installation)])

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            result, _ = await tool._arun_impl(server_url=self.SERVER_URL, tool_name="__list_tools__")
            MockClient.assert_not_called()

        self.assertIn("create_issue", result)
        self.assertIn("Issue title", result)
        self.assertNotIn("delete_everything", result)
        self.assertIn("hidden because the user disabled them", result)

    async def test_list_tools_falls_back_to_upstream_when_cache_empty(self):
        installation = await sync_to_async(self._install_server)(
            name="Linear", url=self.SERVER_URL, auth_type="api_key", sensitive_configuration={"api_key": "k"}
        )
        tool = self._create_tool(installations=[self._inst_dict(installation)])

        raw_tools = [{"name": "fetched", "description": "From upstream", "inputSchema": {}}]
        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = self._make_mock_client()
            mock_instance.list_tools = AsyncMock(return_value=raw_tools)
            MockClient.return_value = mock_instance

            result, _ = await tool._arun_impl(server_url=self.SERVER_URL, tool_name="__list_tools__")
            MockClient.assert_called_once()

        self.assertIn("fetched", result)

    async def test_list_tools_ignores_cache_rows_marked_removed(self):
        def setup():
            installation = self._install_server(
                name="Linear", url=self.SERVER_URL, auth_type="api_key", sensitive_configuration={"api_key": "k"}
            )
            now = timezone.now()
            MCPServerInstallationTool.objects.create(
                installation=installation,
                tool_name="gone",
                approval_state="approved",
                last_seen_at=now,
                removed_at=now,
            )
            return installation

        installation = await sync_to_async(setup)()
        tool = self._create_tool(installations=[self._inst_dict(installation)])

        # Cache is "empty" (only row is removed), so we must hit upstream.
        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = self._make_mock_client()
            mock_instance.list_tools = AsyncMock(return_value=[])
            MockClient.return_value = mock_instance

            result, _ = await tool._arun_impl(server_url=self.SERVER_URL, tool_name="__list_tools__")
            MockClient.assert_called_once()

        self.assertIn("no tools available", result.lower())

    async def test_preview_includes_tool_and_server(self):
        installation = await sync_to_async(self._seed)({"rename_org": "needs_approval"})
        tool = self._create_tool(installations=[self._inst_dict(installation)])
        preview = await tool.format_dangerous_operation_preview(
            server_url=self.SERVER_URL, tool_name="rename_org", arguments={"new_name": "acme"}
        )
        self.assertIn("rename_org", preview)
        self.assertIn("Linear", preview)
        self.assertIn("new_name", preview)
