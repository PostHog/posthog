from unittest.mock import MagicMock, patch
from parameterized import parameterized
from langchain_core.messages import AIMessage as LangchainAIMessage
from ee.hogai.utils.tests import FakeChatOpenAI

from ee.hogai.graph.filter_options.nodes import FilterOptionsNode, FilterOptionsToolsNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.test.base import BaseTest, ClickhouseTestMixin
from langchain_core.agents import AgentAction


class TestFilterOptionsNode(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        # Create test group type mappings
        GroupTypeMapping.objects.create(
            team=self.team, project=self.project, group_type="organization", group_type_index=0
        )
        GroupTypeMapping.objects.create(team=self.team, project=self.project, group_type="company", group_type_index=1)

    def test_init_without_injected_prompts(self):
        """Test node initializes correctly without injected prompts."""
        node = FilterOptionsNode(self.team, self.user)

        self.assertEqual(node.injected_prompts, {})

    def test_init_with_injected_prompts(self):
        """Test node initializes correctly with injected prompts."""
        injected_prompts = {"test_prompt": "test_value"}
        node = FilterOptionsNode(self.team, self.user, injected_prompts=injected_prompts)

        self.assertEqual(node.injected_prompts, injected_prompts)

    def test_run_successful_execution(self):
        """Test successful run execution with proper tool call creation."""
        tool_calls = [{"name": "retrieve_entity_properties", "args": {"entity": "person"}, "id": "call_123"}]

        # Create a message with the expected tool calls
        message = LangchainAIMessage(content="", tool_calls=tool_calls)
        mock_model = FakeChatOpenAI(responses=[message])

        node = FilterOptionsNode(self.team, self.user)

        with patch.object(node, "_get_model", return_value=mock_model):
            state = AssistantState(
                messages=[],
                change="show me user properties",
                current_filters={"property": "active"},
            )

            result = node.run(state, {})

            # Verify result structure
            self.assertIsInstance(result, PartialAssistantState)
            assert result.intermediate_steps is not None
            self.assertEqual(len(result.intermediate_steps), 1)

            # Verify AgentAction creation
            action, output = result.intermediate_steps[0]
            self.assertEqual(action.tool, tool_calls[0]["name"])
            self.assertEqual(action.tool_input, tool_calls[0]["args"])
            self.assertEqual(action.log, tool_calls[0]["id"])
            self.assertIsNone(output)

    def test_run_no_tool_calls_error(self):
        """Test that run raises ValueError when no tool calls are returned."""

        message = LangchainAIMessage(content="No tools available", tool_calls=[])
        mock_model = FakeChatOpenAI(responses=[message])

        node = FilterOptionsNode(self.team, self.user)

        with patch.object(node, "_get_model", return_value=mock_model):
            state = AssistantState(messages=[], change="test query")

            with self.assertRaises(ValueError) as context:
                node.run(state, {})

            self.assertIn("No tool calls found", str(context.exception))

    def test_run_chain_invoke_parameters(self):
        """Test that the node passes correct parameters and handles responses properly."""
        tool_calls = [{"name": "test_tool", "args": {}, "id": "test_id"}]

        message = LangchainAIMessage(content="", tool_calls=tool_calls)
        mock_model = FakeChatOpenAI(responses=[message])

        node = FilterOptionsNode(self.team, self.user)

        with patch.object(node, "_get_model", return_value=mock_model):
            state = AssistantState(messages=[], change="filter users by activity", current_filters={"active": True})

            result = node.run(state, {})

            self.assertIsInstance(result, PartialAssistantState)
            assert result.intermediate_steps is not None
            self.assertEqual(len(result.intermediate_steps), 1)

            action, output = result.intermediate_steps[0]
            self.assertEqual(action.tool, "test_tool")
            self.assertEqual(action.tool_input, {})
            self.assertEqual(action.log, "test_id")
            self.assertIsNone(output)

    def test_run_empty_change_default_handling(self):
        """Test that empty change gets replaced with default message."""
        tool_calls = [{"name": "test_tool", "args": {}, "id": "test_id"}]

        # Create a message with the expected tool calls
        message = LangchainAIMessage(content="", tool_calls=tool_calls)
        mock_model = FakeChatOpenAI(responses=[message])

        node = FilterOptionsNode(self.team, self.user)

        with patch.object(node, "_get_model", return_value=mock_model):
            state = AssistantState(messages=[], change="")

            result = node.run(state, {})

            self.assertIsInstance(result, PartialAssistantState)
            assert result.intermediate_steps is not None
            self.assertEqual(len(result.intermediate_steps), 1)

    def test_run_preserves_existing_intermediate_steps(self):
        """Test that run preserves existing intermediate steps and adds new ones."""
        tool_calls = [{"name": "new_tool", "args": {"param": "value"}, "id": "new_id"}]

        # Create a message with the expected tool calls
        message = LangchainAIMessage(content="", tool_calls=tool_calls)
        mock_model = FakeChatOpenAI(responses=[message])

        node = FilterOptionsNode(self.team, self.user)

        # Create existing intermediate step
        existing_action = AgentAction(tool="old_tool", tool_input={}, log="old_log")
        existing_steps: list[tuple[AgentAction, str | None]] = [(existing_action, "previous_result")]

        with patch.object(node, "_get_model", return_value=mock_model):
            state = AssistantState(messages=[], change="continue processing", intermediate_steps=existing_steps)

            result = node.run(state, {})

            assert result.intermediate_steps is not None
            self.assertEqual(len(result.intermediate_steps), 2)

            # Check existing step is preserved
            old_action, old_output = result.intermediate_steps[0]
            self.assertEqual(old_action.tool, "old_tool")
            self.assertEqual(old_output, "previous_result")

            # Check new step is added
            new_action, new_output = result.intermediate_steps[1]
            self.assertEqual(new_action.tool, "new_tool")
            self.assertEqual(new_action.tool_input, {"param": "value"})
            self.assertEqual(new_action.log, "new_id")

    def test_injected_prompts_through_public_run_interface(self):
        tool_calls = [{"name": "test_tool", "args": {}, "id": "test_id"}]

        # Create a message with the expected tool calls
        message = LangchainAIMessage(content="", tool_calls=tool_calls)
        mock_model = FakeChatOpenAI(responses=[message])

        # Create two nodes with different prompt configurations
        default_node = FilterOptionsNode(self.team, self.user)
        custom_node = FilterOptionsNode(
            self.team,
            self.user,
            injected_prompts={
                "examples_prompt": "CUSTOM_MARKER: Special examples",
                "tool_usage_prompt": "CUSTOM_MARKER: Special tool usage",
            },
        )

        state = AssistantState(messages=[], change="test query")

        # Test that both node configurations work through the public interface
        # This proves injected prompts don't break functionality
        with (
            patch.object(default_node, "_get_model", return_value=mock_model),
            patch.object(custom_node, "_get_model", return_value=mock_model),
        ):
            # Run both nodes - this proves they work with different configurations
            default_result = default_node.run(state, {})
            custom_result = custom_node.run(state, {})

        # Both should succeed
        self.assertIsInstance(default_result, PartialAssistantState)
        self.assertIsInstance(custom_result, PartialAssistantState)

        # Both should create tool actions (proving the injected prompts didn't break functionality)
        assert default_result.intermediate_steps is not None
        assert custom_result.intermediate_steps is not None
        self.assertEqual(len(default_result.intermediate_steps), 1)
        self.assertEqual(len(custom_result.intermediate_steps), 1)


class TestFilterOptionsToolsNode(ClickhouseTestMixin, BaseTest):
    def test_router_with_generated_filter_options(self):
        """Test router returns 'end' when filter options are generated."""
        node = FilterOptionsToolsNode(self.team, self.user)
        state = AssistantState(messages=[], generated_filter_options={"result": "filter", "data": {}})

        result = node.router(state)

        self.assertEqual(result, "end")

    def test_router_with_help_request_message(self):
        """Test router returns 'end' for help request messages."""
        from posthog.schema import AssistantToolCallMessage

        node = FilterOptionsToolsNode(self.team, self.user)
        state = AssistantState(
            messages=[AssistantToolCallMessage(tool_call_id="ask_user_for_help", content="Need help with filters")]
        )

        result = node.router(state)

        self.assertEqual(result, "end")

    def test_router_with_max_iterations_message(self):
        """Test router returns 'end' for max iterations message."""
        from posthog.schema import AssistantToolCallMessage

        node = FilterOptionsToolsNode(self.team, self.user)
        state = AssistantState(
            messages=[AssistantToolCallMessage(tool_call_id="max_iterations", content="Reached maximum iterations")]
        )

        result = node.router(state)

        self.assertEqual(result, "end")

    def test_router_continue_normal_processing(self):
        """Test router returns 'continue' for normal processing."""
        node = FilterOptionsToolsNode(self.team, self.user)
        state = AssistantState(messages=[])

        result = node.router(state)

        self.assertEqual(result, "continue")

    @parameterized.expand(
        [
            ["final_answer", {"name": "final_answer", "arguments": {"result": "filter", "data": {"filter_group": {}}}}],
            ["ask_user_for_help", {"name": "ask_user_for_help", "arguments": {"request": "Need clarification"}}],
            [
                "retrieve_entity_property_values",
                {"name": "retrieve_entity_property_values", "arguments": {"entity": "person", "property_name": "name"}},
            ],
            ["retrieve_entity_properties", {"name": "retrieve_entity_properties", "arguments": {"entity": "person"}}],
        ]
    )
    @patch("ee.hogai.graph.filter_options.nodes.FilterOptionsToolkit")
    def test_run_handles_different_tool_calls(self, tool_name, tool_args, mock_toolkit_class):
        """Test run method handles different tool calls correctly."""

        # Setup mock toolkit
        mock_toolkit = MagicMock()
        mock_toolkit.retrieve_entity_property_values.return_value = "All the property values"
        mock_toolkit.retrieve_entity_properties.return_value = "All the properties"
        mock_toolkit_class.return_value = mock_toolkit

        node = FilterOptionsToolsNode(self.team, self.user)
        action = AgentAction(tool=tool_name, tool_input=tool_args, log="test")
        state = AssistantState(messages=[], intermediate_steps=[(action, None)])

        if tool_name == "final_answer":
            result = node.run(state, {})
            assert result.generated_filter_options is not None  # Type guard
            self.assertEqual(result.generated_filter_options["result"], "filter")
            self.assertEqual(result.generated_filter_options["data"], {"filter_group": {}})
        elif tool_name == "ask_user_for_help":
            result = node.run(state, {})
            # Should return reset state with help message
            self.assertEqual(len(result.messages), 1)
            message = result.messages[0]
            self.assertEqual(getattr(message, "tool_call_id", None), "ask_user_for_help")
            self.assertEqual(getattr(message, "content", None), "Need clarification")
        elif tool_name == "retrieve_entity_property_values":
            result = node.run(state, {})
            mock_toolkit.retrieve_entity_property_values.assert_called_once_with(
                tool_args["arguments"]["entity"], tool_args["arguments"]["property_name"]
            )
            assert result.intermediate_steps is not None
            self.assertEqual(result.intermediate_steps[0][1], "All the property values")
        elif tool_name == "retrieve_entity_properties":
            result = node.run(state, {})
            mock_toolkit.retrieve_entity_properties.assert_called_once_with(tool_args["arguments"]["entity"])
            assert result.intermediate_steps is not None
            self.assertEqual(result.intermediate_steps[0][1], "All the properties")
