from posthog.test.base import NonAtomicBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig

from ee.hogai.tools.read_taxonomy.core import ReadEvents, execute_taxonomy_query
from ee.hogai.tools.read_taxonomy.tool import ReadTaxonomyTool
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath
from ee.models import Conversation


class TestReadTaxonomyTool(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool_call_id = "test_tool_call_id"
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)

    @patch("ee.hogai.tools.read_taxonomy.tool.AssistantContextManager")
    async def test_tool_has_correct_name(self, mock_context_manager_class):
        mock_context_manager = MagicMock()
        mock_context_manager.get_group_names = AsyncMock(return_value=["organization", "project"])
        mock_context_manager_class.return_value = mock_context_manager

        config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})
        tool = await ReadTaxonomyTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
            config=config,
            node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
        )

        self.assertEqual(tool.name, "read_taxonomy")

    @patch("ee.hogai.tools.read_taxonomy.tool.AssistantContextManager")
    async def test_create_tool_class_includes_groups_in_schema(self, mock_context_manager_class):
        mock_context_manager = MagicMock()
        mock_context_manager.get_group_names = AsyncMock(return_value=["organization", "project"])
        mock_context_manager_class.return_value = mock_context_manager

        config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})
        tool = await ReadTaxonomyTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
            config=config,
            node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
        )

        assert tool.args_schema is not None and isinstance(tool.args_schema, type)
        schema = tool.args_schema.model_json_schema()
        entity_properties_schema = schema["$defs"]["ReadEntityProperties"]["properties"]["entity"]

        self.assertIn("organization", entity_properties_schema["enum"])
        self.assertIn("project", entity_properties_schema["enum"])
        self.assertIn("person", entity_properties_schema["enum"])
        self.assertIn("session", entity_properties_schema["enum"])

    @patch("ee.hogai.tools.read_taxonomy.core.TaxonomyAgentToolkit")
    @patch("ee.hogai.tools.read_taxonomy.core.format_events_yaml")
    def test_execute_taxonomy_query_read_events(self, mock_format_events, mock_toolkit_class):
        mock_format_events.return_value = "events:\n  - $pageview\n  - $autocapture"

        result = execute_taxonomy_query(ReadEvents(), mock_toolkit_class.return_value, self.team)

        self.assertIn("events:", result)
        mock_format_events.assert_called_once_with([], self.team)
