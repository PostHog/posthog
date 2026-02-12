from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import AsyncMock, PropertyMock, patch

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from products.mcp_store.backend.models import MCPServer, MCPServerInstallation

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tool_errors import MaxToolRetryableError
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

    def _install_server(self, name="Test Server", url="https://mcp.example.com/mcp"):
        server = MCPServer.objects.create(name=name, url=url)
        return MCPServerInstallation.objects.create(team=self.team, user=self.user, server=server)

    def _create_tool(self, installations: list[dict] | None = None, conversation_id: str | None = None):
        if installations is None:
            installations = []
        allowed_urls = {inst["server__url"] for inst in installations}
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
        await sync_to_async(MCPServerInstallation.objects.create)(team=self.team, user=other_user, server=server)

        tool = await CallMCPServerTool.create_tool_class(
            team=self.team, user=self.user, state=self.state, context_manager=self.context_manager
        )
        self.assertEqual(tool._installations, [])


class TestSSRFPrevention(TestCallMCPServerTool):
    async def test_rejects_url_not_in_installations(self):
        tool = self._create_tool(installations=[{"server__name": "Linear", "server__url": "https://mcp.linear.app"}])
        with self.assertRaises(MaxToolRetryableError) as ctx:
            await tool._arun_impl(server_url="https://evil.com/mcp", tool_name="__list_tools__")
        self.assertIn("not in the user's installed MCP servers", str(ctx.exception))

    async def test_allows_installed_url(self):
        tool = self._create_tool(installations=[{"server__name": "Linear", "server__url": "https://mcp.linear.app"}])
        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            MockClient.return_value = self._make_mock_client()

            result, artifact = await tool._arun_impl(server_url="https://mcp.linear.app", tool_name="__list_tools__")
            self.assertIn("no tools available", result.lower())


class TestListTools(TestCallMCPServerTool):
    async def test_list_tools_returns_formatted_output(self):
        tool = self._create_tool(installations=[{"server__name": "Linear", "server__url": "https://mcp.linear.app"}])
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
        tool = self._create_tool(installations=[{"server__name": "Empty", "server__url": "https://mcp.empty.com"}])
        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            MockClient.return_value = self._make_mock_client()

            result, _ = await tool._arun_impl(server_url="https://mcp.empty.com", tool_name="__list_tools__")
            self.assertIn("no tools available", result.lower())


class TestCallTool(TestCallMCPServerTool):
    async def test_call_tool_returns_result(self):
        tool = self._create_tool(installations=[{"server__name": "Linear", "server__url": "https://mcp.linear.app"}])
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
        tool = self._create_tool(installations=[{"server__name": "Linear", "server__url": "https://mcp.linear.app"}])
        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = self._make_mock_client()
            mock_instance.initialize = AsyncMock(side_effect=MCPClientError("Connection refused"))
            MockClient.return_value = mock_instance

            with self.assertRaises(MaxToolRetryableError) as ctx:
                await tool._arun_impl(server_url="https://mcp.linear.app", tool_name="create_issue", arguments={})
            self.assertIn("MCP server error", str(ctx.exception))

    async def test_timeout_becomes_retryable(self):
        tool = self._create_tool(installations=[{"server__name": "Slow", "server__url": "https://mcp.slow.com"}])
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
    INSTALLATIONS = [{"server__name": "Linear", "server__url": "https://mcp.linear.app"}]

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
        self.assertEqual(result[0]["server__name"], "Linear")
        self.assertEqual(result[0]["server__url"], "https://mcp.linear.app")

    def test_returns_empty_when_none_installed(self):
        result = _get_installations(self.team, self.user)
        self.assertEqual(result, [])
