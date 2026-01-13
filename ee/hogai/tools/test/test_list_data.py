from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.tools.list_data import ListDataTool
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath


class TestListDataTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool_call_id = "test_tool_call_id"
        self.state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        self.context_manager = AssistantContextManager(self.team, self.user, {})
        self.tool = ListDataTool(
            team=self.team,
            user=self.user,
            state=self.state,
            context_manager=self.context_manager,
            node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
        )

    async def test_list_entities_returns_formatted_data(self):
        """Test that list entities returns formatted entity data."""
        entities_data = [
            {
                "type": "insight",
                "result_id": "insight-123",
                "extra_fields": {"name": "Test Insight", "description": "A test insight"},
            }
        ]
        formatted_str = "Entity type: Insight\nID|Name|Description|URL\ninsight-123|Test Insight|A test insight|-"

        with patch("ee.hogai.tools.list_data.EntitySearchContext") as MockEntitySearchContext:
            mock_instance = MagicMock()
            mock_instance.list_entities = AsyncMock(return_value=(entities_data, 1))
            mock_instance.format_entities = MagicMock(return_value=formatted_str)
            MockEntitySearchContext.return_value = mock_instance

            result, _ = await self.tool._arun_impl(kind="insights", limit=100, offset=0)

            MockEntitySearchContext.assert_called_once_with(
                team=self.team, user=self.user, context_manager=self.context_manager
            )
            mock_instance.list_entities.assert_called_once_with("insight", 100, 0)
            mock_instance.format_entities.assert_called_once_with(entities_data)

            self.assertIn("Offset 0, limit 100", result)
            self.assertIn("Test Insight", result)
            self.assertIn("insight-123", result)
            self.assertIn("You reached the end of results", result)

    async def test_list_entities_with_pagination(self):
        """Test list entities pagination."""
        entities_data = [
            {"type": "dashboard", "result_id": "dash-1", "extra_fields": {"name": "Dashboard 1"}},
            {"type": "dashboard", "result_id": "dash-2", "extra_fields": {"name": "Dashboard 2"}},
        ]
        formatted_str = "Entity type: Dashboard\nID|Name|URL\ndash-1|Dashboard 1|-\ndash-2|Dashboard 2|-"

        with patch("ee.hogai.tools.list_data.EntitySearchContext") as MockEntitySearchContext:
            mock_instance = MagicMock()
            mock_instance.list_entities = AsyncMock(return_value=(entities_data, 5))
            mock_instance.format_entities = MagicMock(return_value=formatted_str)
            MockEntitySearchContext.return_value = mock_instance

            result, _ = await self.tool._arun_impl(kind="dashboards", limit=2, offset=0)

            self.assertIn("Offset 0, limit 2", result)
            self.assertIn("To see more results, use offset=2", result)
            self.assertIn("Dashboard 1", result)
            self.assertIn("Dashboard 2", result)

    async def test_list_entities_rejects_all_kind(self):
        """Test that list entities rejects 'all' as entity kind."""
        with self.assertRaises(MaxToolRetryableError) as context:
            await self.tool._arun_impl(kind="all", limit=100, offset=0)

        error_message = str(context.exception)
        self.assertIn("Invalid entity kind for listing", error_message)

    async def test_list_entities_rejects_invalid_kind(self):
        """Test that list entities rejects invalid entity kinds."""
        with self.assertRaises(ValueError):
            await self.tool._arun_impl(kind="invalid_kind", limit=100, offset=0)

    async def test_list_entities_default_pagination(self):
        """Test that list entities uses default pagination values."""
        entities_data = [
            {"type": "insight", "result_id": "insight-1", "extra_fields": {"name": "Insight 1"}},
        ]
        formatted_str = "Entity type: Insight\nID|Name|URL\ninsight-1|Insight 1|-"

        with patch("ee.hogai.tools.list_data.EntitySearchContext") as MockEntitySearchContext:
            mock_instance = MagicMock()
            mock_instance.list_entities = AsyncMock(return_value=(entities_data, 1))
            mock_instance.format_entities = MagicMock(return_value=formatted_str)
            MockEntitySearchContext.return_value = mock_instance

            result, _ = await self.tool._arun_impl(kind="insights", limit=100, offset=0)

            mock_instance.list_entities.assert_called_once_with("insight", 100, 0)
            self.assertIn("Offset 0, limit 100", result)

    async def test_list_artifacts_returns_formatted_data(self):
        """Test that artifacts kind returns formatted artifact data."""
        entities_data = [
            {
                "type": "artifact",
                "result_id": "artifact-123",
                "extra_fields": {"name": "Test Chart", "description": "A test visualization"},
            }
        ]
        formatted_str = "Entity type: Artifact\nID|Name|Description|URL\nartifact-123|Test Chart|A test visualization|-"

        with patch("ee.hogai.tools.list_data.EntitySearchContext") as MockEntitySearchContext:
            mock_instance = MagicMock()
            mock_instance.list_entities = AsyncMock(return_value=(entities_data, 1))
            mock_instance.format_entities = MagicMock(return_value=formatted_str)
            MockEntitySearchContext.return_value = mock_instance

            result, _ = await self.tool._arun_impl(kind="artifacts", limit=100, offset=0)

            MockEntitySearchContext.assert_called_once_with(
                team=self.team, user=self.user, context_manager=self.context_manager
            )
            mock_instance.list_entities.assert_called_once_with("artifact", 100, 0)
            mock_instance.format_entities.assert_called_once_with(entities_data)

            self.assertIn("Offset 0, limit 100", result)
            self.assertIn("Test Chart", result)
            self.assertIn("Artifact", result)
            self.assertIn("artifact-123", result)
            self.assertIn("You reached the end of results", result)

    async def test_list_artifacts_returns_empty_results(self):
        """Test that artifacts kind returns empty results when no entities found."""
        with patch("ee.hogai.tools.list_data.EntitySearchContext") as MockEntitySearchContext:
            mock_instance = MagicMock()
            mock_instance.list_entities = AsyncMock(return_value=([], 0))
            mock_instance.format_entities = MagicMock(return_value="")
            MockEntitySearchContext.return_value = mock_instance

            result, _ = await self.tool._arun_impl(kind="artifacts", limit=100, offset=0)

            mock_instance.list_entities.assert_called_once_with("artifact", 100, 0)
            self.assertIn("Offset 0, limit 100", result)
            self.assertIn("You reached the end of results", result)

    async def test_list_artifacts_with_pagination(self):
        """Test pagination functionality with multiple pages."""
        # First page: offset=0, limit=2, total=5
        first_page_data = [
            {"type": "artifact", "result_id": "artifact-1", "extra_fields": {"name": "Chart 1"}},
            {"type": "artifact", "result_id": "artifact-2", "extra_fields": {"name": "Chart 2"}},
        ]
        first_page_str = "Entity type: Artifact\nID|Name|URL\nartifact-1|Chart 1|-\nartifact-2|Chart 2|-"

        with patch("ee.hogai.tools.list_data.EntitySearchContext") as MockEntitySearchContext:
            mock_instance = MagicMock()
            mock_instance.list_entities = AsyncMock(return_value=(first_page_data, 5))
            mock_instance.format_entities = MagicMock(return_value=first_page_str)
            MockEntitySearchContext.return_value = mock_instance

            result, _ = await self.tool._arun_impl(kind="artifacts", limit=2, offset=0)

            self.assertIn("Offset 0, limit 2", result)
            self.assertIn("To see more results, use offset=2", result)
            self.assertIn("Chart 1", result)
            self.assertIn("Chart 2", result)

        # Last page: offset=4, limit=2, total=5 (only 1 item left)
        last_page_data = [
            {"type": "artifact", "result_id": "artifact-5", "extra_fields": {"name": "Chart 5"}},
        ]
        last_page_str = "Entity type: Artifact\nID|Name|URL\nartifact-5|Chart 5|-"

        with patch("ee.hogai.tools.list_data.EntitySearchContext") as MockEntitySearchContext:
            mock_instance = MagicMock()
            mock_instance.list_entities = AsyncMock(return_value=(last_page_data, 5))
            mock_instance.format_entities = MagicMock(return_value=last_page_str)
            MockEntitySearchContext.return_value = mock_instance

            result, _ = await self.tool._arun_impl(kind="artifacts", limit=2, offset=4)

            self.assertIn("Offset 4, limit 2", result)
            self.assertIn("You reached the end of results", result)
            self.assertIn("Chart 5", result)
