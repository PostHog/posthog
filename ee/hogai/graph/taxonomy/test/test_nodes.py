from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from langchain_core.agents import AgentAction
from langchain_core.runnables import RunnableConfig
from parameterized import parameterized
from pydantic import ValidationError

from ee.hogai.graph.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit
from ee.hogai.graph.taxonomy.types import TaxonomyAgentState


class MockTaxonomyAgentToolkit(TaxonomyAgentToolkit):
    def get_tools(self):
        from pydantic import BaseModel

        class MockTool(BaseModel):
            test_field: str = "test"

        return [MockTool]


class ConcreteTaxonomyAgentNode(TaxonomyAgentNode[TaxonomyAgentState, TaxonomyAgentState]):
    def _get_system_prompt(self):
        from langchain_core.prompts import ChatPromptTemplate

        return ChatPromptTemplate([("system", "test system prompt")])


class ConcreteTaxonomyAgentToolsNode(TaxonomyAgentToolsNode[TaxonomyAgentState, TaxonomyAgentState]):
    pass


class TestTaxonomyAgentNode(BaseTest):
    def setUp(self):
        super().setUp()
        self.node = ConcreteTaxonomyAgentNode(self.team, self.user, MockTaxonomyAgentToolkit)

    def test_node_initialization(self):
        self.assertEqual(self.node._team, self.team)
        self.assertEqual(self.node._user, self.user)
        self.assertIsInstance(self.node._toolkit, MockTaxonomyAgentToolkit)

    def test_get_state_class(self):
        state_class, partial_state_class = self.node._get_state_class(TaxonomyAgentNode)
        self.assertEqual(state_class, TaxonomyAgentState)
        self.assertEqual(partial_state_class, TaxonomyAgentState)

    def test_get_system_prompt_concrete_implementation(self):
        prompts = self.node._get_system_prompt()
        self.assertTrue(len(prompts.messages) == 1)
        self.assertEqual(prompts.messages[0].prompt.template, "test system prompt")

    def test_construct_messages(self):
        from langchain_core.messages import HumanMessage

        state = TaxonomyAgentState()
        state.tool_progress_messages = [HumanMessage(content="test message")]

        result = self.node._construct_messages(state)

        self.assertIsNotNone(result)
        self.assertTrue(len(result.messages) > 0)

    @patch("ee.hogai.graph.taxonomy.nodes.merge_message_runs")
    @patch("ee.hogai.graph.taxonomy.nodes.format_events_yaml")
    def test_run_basic_flow(self, mock_format_events, mock_merge):
        mock_format_events.return_value = "formatted events"
        mock_merge.return_value = Mock()

        # Mock the model chain
        mock_chain = Mock()
        mock_output = Mock()
        mock_output.tool_calls = [{"name": "test_tool", "args": {"param": "value"}, "id": "tool_id"}]
        mock_output.content = "test content"
        mock_output.id = "message_id"
        mock_chain.invoke.return_value = mock_output

        with (
            patch.object(self.node, "_construct_messages") as mock_construct,
            patch.object(self.node, "_get_model") as mock_get_model,
        ):
            mock_template = Mock()
            mock_construct.return_value = mock_template
            mock_model = Mock()
            mock_get_model.return_value = mock_model

            # Create the chain: template | merge | model
            mock_template.__or__ = Mock(return_value=Mock())
            mock_template.__or__.return_value.__or__ = Mock(return_value=mock_chain)

            state = TaxonomyAgentState()
            state.instructions = "test change"
            state.output = {"test": "filter"}

            config = RunnableConfig()
            result = self.node.run(state, config)

            self.assertIsInstance(result, TaxonomyAgentState)
            self.assertEqual(len(result.intermediate_steps), 1)
            self.assertEqual(len(result.tool_progress_messages), 1)
            self.assertEqual(result.intermediate_steps[0][0].tool, "test_tool")
            self.assertEqual(result.intermediate_steps[0][0].tool_input, {"param": "value"})

    @patch("ee.hogai.graph.taxonomy.nodes.merge_message_runs")
    @patch("ee.hogai.graph.taxonomy.nodes.format_events_yaml")
    def test_run_no_tool_calls_error(self, mock_format_events, mock_merge):
        with (
            patch.object(self.node, "_construct_messages") as mock_construct,
            patch.object(self.node, "_get_model") as mock_get_model,
        ):
            mock_chain = Mock()
            mock_output = Mock()
            mock_output.tool_calls = []  # No tool calls
            mock_chain.invoke.return_value = mock_output

            mock_template = Mock()
            mock_construct.return_value = mock_template
            mock_model = Mock()
            mock_get_model.return_value = mock_model

            mock_template.__or__ = Mock(return_value=Mock())
            mock_template.__or__.return_value.__or__ = Mock(return_value=mock_chain)

            state = TaxonomyAgentState()

            with self.assertRaises(ValueError) as context:
                self.node.run(state, RunnableConfig())

            self.assertIn("No tool calls found", str(context.exception))


class TestTaxonomyAgentToolsNode(BaseTest):
    def setUp(self):
        super().setUp()
        self.node = ConcreteTaxonomyAgentToolsNode(self.team, self.user, MockTaxonomyAgentToolkit)

    def test_node_initialization(self):
        self.assertEqual(self.node._team, self.team)
        self.assertEqual(self.node._user, self.user)
        self.assertIsInstance(self.node._toolkit, MockTaxonomyAgentToolkit)
        self.assertEqual(self.node.MAX_ITERATIONS, 10)

    def test_get_state_class(self):
        state_class, partial_state_class = self.node._get_state_class(TaxonomyAgentToolsNode)
        self.assertEqual(state_class, TaxonomyAgentState)
        self.assertEqual(partial_state_class, TaxonomyAgentState)

    def test_get_state_class_no_generic_error(self):
        # Test error case for non-generic class
        class NonGenericToolsNode(TaxonomyAgentToolsNode):
            pass

        with self.assertRaises(ValueError) as context:
            NonGenericToolsNode(self.team, self.user, MockTaxonomyAgentToolkit)

        self.assertIn("Could not determine state type", str(context.exception))

    @patch.object(MockTaxonomyAgentToolkit, "get_tool_input_model")
    @patch.object(MockTaxonomyAgentToolkit, "handle_tools")
    async def test_run_normal_tool_execution(self, mock_handle_tools, mock_get_tool_input):
        # Setup mocks
        mock_input = Mock()
        mock_input.name = "test_tool"
        mock_input.arguments = Mock()
        mock_get_tool_input.return_value = mock_input
        mock_handle_tools.return_value = ("test_tool", "tool output")

        # Create state with intermediate step
        action = AgentAction(tool="test_tool", tool_input={"param": "value"}, log="test_log")
        state = TaxonomyAgentState()
        state.intermediate_steps = [(action, None)]

        result = await self.node.arun(state, RunnableConfig())

        self.assertIsInstance(result, TaxonomyAgentState)
        self.assertEqual(len(result.intermediate_steps), 1)
        self.assertEqual(result.intermediate_steps[0][1], "tool output")

    @patch.object(MockTaxonomyAgentToolkit, "get_tool_input_model")
    async def test_run_validation_error(self, mock_get_tool_input):
        # Setup validation error
        validation_error = ValidationError.from_exception_data(
            "TestModel", [{"type": "missing", "loc": ("field",), "msg": "Field required"}]
        )
        mock_get_tool_input.side_effect = validation_error

        action = AgentAction(tool="test_tool", tool_input={}, log="test_log")
        state = TaxonomyAgentState()
        state.intermediate_steps = [(action, None)]

        result = await self.node.arun(state, RunnableConfig())

        self.assertIsInstance(result, TaxonomyAgentState)
        self.assertEqual(len(result.tool_progress_messages), 1)

    @patch.object(MockTaxonomyAgentToolkit, "get_tool_input_model")
    async def test_run_final_answer(self, mock_get_tool_input):
        # Mock final answer tool
        from pydantic import BaseModel

        class ExpectedDataModel(BaseModel):
            result: str

        expected_data = ExpectedDataModel(result="final result")

        # Create a simple mock that provides the expected structure
        mock_input = Mock()
        mock_input.name = "final_answer"
        mock_input.arguments = Mock()
        mock_input.arguments.answer = expected_data

        action = AgentAction(tool="final_answer", tool_input={"data": expected_data.model_dump()}, log="test_log")
        mock_get_tool_input.return_value = mock_input
        state = TaxonomyAgentState()
        state.intermediate_steps = [(action, None)]

        result = await self.node.arun(state, RunnableConfig())

        self.assertIsInstance(result, TaxonomyAgentState)
        self.assertEqual(result.output, expected_data)
        self.assertIsNone(result.intermediate_steps)

    @patch.object(MockTaxonomyAgentToolkit, "get_tool_input_model")
    async def test_run_ask_user_for_help(self, mock_get_tool_input):
        # Mock ask for help tool
        mock_input = Mock()
        mock_input.name = "ask_user_for_help"
        mock_input.arguments = Mock()
        mock_input.arguments.request = "Need help"
        mock_get_tool_input.return_value = mock_input

        action = AgentAction(tool="ask_user_for_help", tool_input={"request": "Need help"}, log="test_log")
        state = TaxonomyAgentState()
        state.intermediate_steps = [(action, None)]

        with patch.object(self.node, "_get_reset_state") as mock_reset:
            mock_reset.return_value = TaxonomyAgentState()

            _ = await self.node.arun(state, RunnableConfig())

            mock_reset.assert_called_once_with("Need help", "ask_user_for_help", state)

    async def test_run_max_iterations(self):
        # Create state with max iterations
        actions = []
        for i in range(self.node.MAX_ITERATIONS):
            action = AgentAction(tool=f"tool_{i}", tool_input={}, log=f"log_{i}")
            actions.append((action, None))

        state = TaxonomyAgentState()
        state.intermediate_steps = actions

        with patch.object(self.node, "_get_reset_state") as mock_reset:
            mock_reset.return_value = TaxonomyAgentState()

            _ = await self.node.arun(state, RunnableConfig())

            mock_reset.assert_called_once()
            call_args = mock_reset.call_args
            self.assertEqual(call_args[0][1], "max_iterations")

    @parameterized.expand(
        [
            ("has_output", "end"),
            ("final_answer", "end"),  # final_answer tool returns continue, not end
            ("ask_user_for_help", "end"),
            ("max_iterations", "end"),
            ("normal_tool", "continue"),
        ]
    )
    def test_router(self, scenario, expected):
        state = TaxonomyAgentState()
        if scenario == "has_output":
            state.output = {"result": "test"}  # Has output
        elif scenario == "final_answer":
            state.output = {"result": "test"}
            state.intermediate_steps = [(AgentAction("final_answer", {}, ""), None)]
        elif scenario == "ask_user_for_help":
            state.output = "I need more information to proceed."
            state.intermediate_steps = [(AgentAction("ask_user_for_help", {}, ""), None)]
        elif scenario == "max_iterations":
            state.output = "MAX_ITERATIONS"
            state.intermediate_steps = [(AgentAction("max_iterations", {}, ""), None)]
        elif scenario == "normal_tool":
            state.intermediate_steps = [(AgentAction("normal_tool", {}, ""), "result")]

        result = self.node.router(state)
        self.assertEqual(result, expected)

    async def test_get_reset_state(self):
        original_state = TaxonomyAgentState()
        original_state.change = "test change"

        with patch.object(TaxonomyAgentState, "get_reset_state") as mock_get_reset:
            mock_reset_state = TaxonomyAgentState()
            mock_get_reset.return_value = mock_reset_state

            result = self.node._get_reset_state("test output", "test_tool", original_state)

            self.assertEqual(len(result.intermediate_steps), 1)
            action, output = result.intermediate_steps[0]
            self.assertEqual(action.tool, "test_tool")
            self.assertEqual(action.tool_input, "test output")
            self.assertIsNone(output)
