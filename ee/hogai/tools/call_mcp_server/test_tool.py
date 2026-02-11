from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import AsyncMock, patch

from asgiref.sync import sync_to_async

from products.mcp_store.backend.models import MCPServer, MCPServerInstallation

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.tools.call_mcp_server.mcp_client import MCPClientError
from ee.hogai.tools.call_mcp_server.tool import CallMCPServerTool, _get_installations
from ee.hogai.utils.types.base import AssistantState, NodePath


class TestCallMCPServerTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.state = AssistantState(messages=[])
        self.context_manager = AssistantContextManager(self.team, self.user, {})
        self.node_path = (NodePath(name="test_node", tool_call_id="test_call", message_id="test"),)

    def _install_server(self, name="Test Server", url="https://mcp.example.com/mcp"):
        server = MCPServer.objects.create(team=self.team, name=name, url=url)
        return MCPServerInstallation.objects.create(team=self.team, user=self.user, server=server)

    def _create_tool(self, installations: list[dict] | None = None):
        if installations is None:
            installations = []
        allowed_urls = {inst["server__url"] for inst in installations}
        description = "test"
        tool = CallMCPServerTool(
            team=self.team,
            user=self.user,
            state=self.state,
            context_manager=self.context_manager,
            node_path=self.node_path,
            description=description,
        )
        tool._allowed_server_urls = allowed_urls
        tool._installations = installations
        return tool


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
        server = await sync_to_async(MCPServer.objects.create)(
            team=self.team, name="Other Server", url="https://mcp.other.com"
        )
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
            mock_instance = AsyncMock()
            mock_instance.initialize = AsyncMock(return_value={})
            mock_instance.list_tools = AsyncMock(return_value=[])
            MockClient.return_value = mock_instance

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
            mock_instance = AsyncMock()
            mock_instance.initialize = AsyncMock(return_value={})
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
            mock_instance = AsyncMock()
            mock_instance.initialize = AsyncMock(return_value={})
            mock_instance.list_tools = AsyncMock(return_value=[])
            MockClient.return_value = mock_instance

            result, _ = await tool._arun_impl(server_url="https://mcp.empty.com", tool_name="__list_tools__")
            self.assertIn("no tools available", result.lower())


class TestCallTool(TestCallMCPServerTool):
    async def test_call_tool_returns_result(self):
        tool = self._create_tool(installations=[{"server__name": "Linear", "server__url": "https://mcp.linear.app"}])
        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.initialize = AsyncMock(return_value={})
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
            mock_instance = AsyncMock()
            mock_instance.initialize = AsyncMock(side_effect=MCPClientError("Connection refused"))
            MockClient.return_value = mock_instance

            with self.assertRaises(MaxToolRetryableError) as ctx:
                await tool._arun_impl(server_url="https://mcp.linear.app", tool_name="create_issue", arguments={})
            self.assertIn("MCP server error", str(ctx.exception))

    async def test_timeout_becomes_retryable(self):
        tool = self._create_tool(installations=[{"server__name": "Slow", "server__url": "https://mcp.slow.com"}])
        import httpx as _httpx

        with patch("ee.hogai.tools.call_mcp_server.tool.MCPClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.initialize = AsyncMock(side_effect=_httpx.TimeoutException("timed out"))
            MockClient.return_value = mock_instance

            with self.assertRaises(MaxToolRetryableError) as ctx:
                await tool._arun_impl(server_url="https://mcp.slow.com", tool_name="some_tool", arguments={})
            self.assertIn("timed out", str(ctx.exception))


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
