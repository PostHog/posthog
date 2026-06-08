import pytest
from posthog.test.base import NonAtomicBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.tools.read_taxonomy.core import (
    DYNAMIC_EVENT_PROPERTIES_HINT,
    DYNAMIC_PERSON_PROPERTIES_HINT,
    ReadEntityProperties,
    ReadEventProperties,
    ReadEvents,
    execute_taxonomy_query,
)
from ee.hogai.tools.read_taxonomy.tool import ReadTaxonomyTool
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath


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

        assert tool.name == "read_taxonomy"

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

        assert "organization" in entity_properties_schema["enum"]
        assert "project" in entity_properties_schema["enum"]
        assert "person" in entity_properties_schema["enum"]
        assert "session" in entity_properties_schema["enum"]

    @parameterized.expand(
        [
            ("wrong_field_name", {"kind": "event_properties", "event": "$pageview"}, "event_name"),
            ("wrong_discriminator_value", {"kind": "ReadEvents"}, "ReadEvents"),
            (
                "missing_required_field",
                {"kind": "event_property_values", "event_name": "$pageview"},
                "property_name",
            ),
        ]
    )
    @patch("ee.hogai.tools.read_taxonomy.tool.AssistantContextManager")
    async def test_run_impl_wraps_validation_error_in_retryable_error(
        self, _name, query, expected_match, mock_context_manager_class
    ):
        mock_context_manager = MagicMock()
        mock_context_manager.get_group_names = AsyncMock(return_value=[])
        mock_context_manager_class.return_value = mock_context_manager

        config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})
        tool = await ReadTaxonomyTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
            config=config,
            node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
        )

        with pytest.raises(MaxToolRetryableError, match=expected_match):
            tool._run_impl(query=query)

    @patch("ee.hogai.tools.read_taxonomy.core.TaxonomyAgentToolkit")
    @patch("ee.hogai.tools.read_taxonomy.core.format_events_yaml")
    def test_execute_taxonomy_query_read_events(self, mock_format_events, mock_toolkit_class):
        mock_format_events.return_value = "events:\n  - $pageview\n  - $autocapture"

        result = execute_taxonomy_query(ReadEvents(), mock_toolkit_class.return_value, self.team)

        assert "events:" in result
        mock_format_events.assert_called_once_with([], self.team, limit=500, offset=0)

    @patch("ee.hogai.tools.read_taxonomy.core.TaxonomyAgentToolkit")
    def test_person_entity_properties_include_dynamic_hint(self, mock_toolkit_class):
        mock_toolkit = mock_toolkit_class.return_value
        mock_toolkit.retrieve_entity_properties.return_value = "- email\n- name"

        result = execute_taxonomy_query(ReadEntityProperties(entity="person"), mock_toolkit, self.team)

        assert DYNAMIC_PERSON_PROPERTIES_HINT in result
        assert "$survey_dismissed" in result
        assert "$feature_enrollment" in result
        assert "$product_tour_dismissed" in result

    @patch("ee.hogai.tools.read_taxonomy.core.TaxonomyAgentToolkit")
    def test_non_person_entity_properties_exclude_dynamic_hint(self, mock_toolkit_class):
        mock_toolkit = mock_toolkit_class.return_value
        mock_toolkit.retrieve_entity_properties.return_value = "- $start_timestamp"

        result = execute_taxonomy_query(ReadEntityProperties(entity="session"), mock_toolkit, self.team)

        assert DYNAMIC_PERSON_PROPERTIES_HINT not in result

    @patch("ee.hogai.tools.read_taxonomy.core.TaxonomyAgentToolkit")
    def test_event_properties_include_dynamic_hint(self, mock_toolkit_class):
        mock_toolkit = mock_toolkit_class.return_value
        mock_toolkit.retrieve_event_or_action_properties.return_value = "- $browser\n- $os"

        result = execute_taxonomy_query(ReadEventProperties(event_name="$pageview"), mock_toolkit, self.team)

        assert DYNAMIC_EVENT_PROPERTIES_HINT in result
        assert "$feature/{flag_key}" in result
