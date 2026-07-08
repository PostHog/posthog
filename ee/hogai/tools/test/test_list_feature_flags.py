from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import patch

from parameterized import parameterized

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tools.list_feature_flags import ListFeatureFlagsTool
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath


class TestListFeatureFlagsTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool_call_id = "test_tool_call_id"
        self.state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        self.context_manager = AssistantContextManager(self.team, self.user, {})
        self.tool = ListFeatureFlagsTool(
            team=self.team,
            user=self.user,
            state=self.state,
            context_manager=self.context_manager,
            node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
        )

    @parameterized.expand(
        [
            ("stale", "STALE"),
            ("enabled", "true"),
            ("disabled", "false"),
            (None, None),
        ]
    )
    async def test_status_maps_to_active_filter(self, status, expected_active_filter):
        """The user-facing status maps to the backend `active` query param."""
        # autospec validates calls against the real EntitySearchContext signature
        with patch("ee.hogai.tools.list_feature_flags.EntitySearchContext", autospec=True) as MockEntitySearchContext:
            mock_instance = MockEntitySearchContext.return_value
            mock_instance.list_feature_flags.return_value = ([], 0)
            mock_instance.format_entities.return_value = ""

            await self.tool._arun_impl(status=status, limit=100, offset=0)

            MockEntitySearchContext.assert_called_once_with(
                team=self.team, user=self.user, context_manager=self.context_manager
            )
            mock_instance.list_feature_flags.assert_called_once_with(100, 0, active_filter=expected_active_filter)

    async def test_returns_formatted_data_with_status(self):
        """Results carry each flag's status so stale flags are identifiable without per-flag reads."""
        entities_data = [
            {
                "type": "feature_flag",
                "result_id": "123",
                "extra_fields": {"key": "my-flag", "name": "My flag", "status": "stale", "active": True},
            }
        ]
        formatted_str = (
            "entity_type: feature_flag\nfeature_flag_id|name|active|key|status|url\n123|My flag|True|my-flag|stale|-"
        )

        with patch("ee.hogai.tools.list_feature_flags.EntitySearchContext", autospec=True) as MockEntitySearchContext:
            mock_instance = MockEntitySearchContext.return_value
            mock_instance.list_feature_flags.return_value = (entities_data, 1)
            mock_instance.format_entities.return_value = formatted_str

            result, _ = await self.tool._arun_impl(status="stale", limit=100, offset=0)

            mock_instance.format_entities.assert_called_once_with(entities_data)
            self.assertIn("Offset 0, limit 100", result)
            self.assertIn("my-flag", result)
            self.assertIn("stale", result)
            self.assertIn("You reached the end of results", result)

    async def test_pagination_indicates_more_results(self):
        """When there are more flags than the page, the next offset is surfaced."""
        with patch("ee.hogai.tools.list_feature_flags.EntitySearchContext", autospec=True) as MockEntitySearchContext:
            mock_instance = MockEntitySearchContext.return_value
            mock_instance.list_feature_flags.return_value = ([], 5)
            mock_instance.format_entities.return_value = ""

            result, _ = await self.tool._arun_impl(status=None, limit=2, offset=0)

            self.assertIn("To see more results, use offset=2", result)
