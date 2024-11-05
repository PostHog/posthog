from unittest.mock import patch

from django.test import override_settings
from langchain_core.agents import AgentAction
from langchain_core.messages import AIMessage as LangchainAIMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda

from ee.hogai.taxonomy_agent.nodes import (
    ChatPromptTemplate,
    TaxonomyAgentPlannerNode,
    TaxonomyAgentPlannerToolsNode,
)
from ee.hogai.taxonomy_agent.toolkit import TaxonomyAgentToolkit, ToolkitTool
from ee.hogai.utils import AssistantState
from posthog.schema import (
    AssistantMessage,
    ExperimentalAITrendsQuery,
    FailureMessage,
    HumanMessage,
    VisualizationMessage,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person


class TestToolkit(TaxonomyAgentToolkit):
    def _get_tools(self) -> list[ToolkitTool]:
        return self._default_tools


@override_settings(IN_UNIT_TESTING=True)
class TestTaxonomyAgentPlannerNode(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.schema = ExperimentalAITrendsQuery(series=[])

    def _get_node(self):
        class Node(TaxonomyAgentPlannerNode):
            def run(self, state: AssistantState, config: RunnableConfig) -> AssistantState:
                prompt = ChatPromptTemplate.from_messages([("user", "test")])
                toolkit = TestToolkit(self._team)
                return super()._run(state, prompt, toolkit, config=config)

        return Node(self.team)

    def test_agent_reconstructs_conversation(self):
        node = self._get_node()
        history = node._reconstruct_conversation({"messages": [HumanMessage(content="Text")]})
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Text", history[0].content)
        self.assertNotIn(f"{{question}}", history[0].content)

        history = node._reconstruct_conversation(
            {
                "messages": [
                    HumanMessage(content="Text"),
                    VisualizationMessage(answer=self.schema, plan="randomplan"),
                ]
            }
        )
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Text", history[0].content)
        self.assertNotIn("{{question}}", history[0].content)
        self.assertEqual(history[1].type, "ai")
        self.assertEqual(history[1].content, "randomplan")

        history = node._reconstruct_conversation(
            {
                "messages": [
                    HumanMessage(content="Text"),
                    VisualizationMessage(answer=self.schema, plan="randomplan"),
                    HumanMessage(content="Text"),
                ]
            }
        )
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Text", history[0].content)
        self.assertNotIn("{{question}}", history[0].content)
        self.assertEqual(history[1].type, "ai")
        self.assertEqual(history[1].content, "randomplan")
        self.assertEqual(history[2].type, "human")
        self.assertIn("Text", history[2].content)
        self.assertNotIn("{{question}}", history[2].content)

    def test_agent_reconstructs_conversation_and_omits_unknown_messages(self):
        node = self._get_node()
        history = node._reconstruct_conversation(
            {
                "messages": [
                    HumanMessage(content="Text"),
                    AssistantMessage(content="test"),
                ]
            }
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Text", history[0].content)
        self.assertNotIn("{{question}}", history[0].content)

    def test_agent_reconstructs_conversation_with_failures(self):
        node = self._get_node()
        history = node._reconstruct_conversation(
            {
                "messages": [
                    HumanMessage(content="Text"),
                    FailureMessage(content="Error"),
                    HumanMessage(content="Text"),
                ]
            }
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Text", history[0].content)
        self.assertNotIn("{{question}}", history[0].content)

    def test_agent_filters_out_low_count_events(self):
        _create_person(distinct_ids=["test"], team=self.team)
        for i in range(26):
            _create_event(event=f"event{i}", distinct_id="test", team=self.team)
            _create_event(event="distinctevent", distinct_id="test", team=self.team)
        node = self._get_node()
        self.assertEqual(
            node._events_prompt,
            "<list of available events for filtering>\nall events\ndistinctevent\n</list of available events for filtering>",
        )

    def test_agent_preserves_low_count_events_for_smaller_teams(self):
        _create_person(distinct_ids=["test"], team=self.team)
        _create_event(event="distinctevent", distinct_id="test", team=self.team)
        node = self._get_node()
        self.assertIn("distinctevent", node._events_prompt)
        self.assertIn("all events", node._events_prompt)

    def test_agent_scratchpad(self):
        node = self._get_node()
        scratchpad = [
            (AgentAction(tool="test1", tool_input="input1", log="log1"), "test"),
            (AgentAction(tool="test2", tool_input="input2", log="log2"), None),
            (AgentAction(tool="test3", tool_input="input3", log="log3"), ""),
        ]
        prompt = node._get_agent_scratchpad(scratchpad)
        self.assertIn("log1", prompt)
        self.assertIn("log3", prompt)

    def test_agent_handles_output_without_action_block(self):
        with patch(
            "ee.hogai.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model",
            return_value=RunnableLambda(lambda _: LangchainAIMessage(content="I don't want to output an action.")),
        ):
            node = self._get_node()
            state_update = node.run({"messages": [HumanMessage(content="Question")]}, {})
            self.assertEqual(len(state_update["intermediate_steps"]), 1)
            action, obs = state_update["intermediate_steps"][0]
            self.assertIsNone(obs)
            self.assertIn("I don't want to output an action.", action.log)
            self.assertIn("Action:", action.log)
            self.assertIn("Action:", action.tool_input)

    def test_agent_handles_output_with_malformed_json(self):
        with patch(
            "ee.hogai.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model",
            return_value=RunnableLambda(lambda _: LangchainAIMessage(content="Thought.\nAction: abc")),
        ):
            node = self._get_node()
            state_update = node.run({"messages": [HumanMessage(content="Question")]}, {})
            self.assertEqual(len(state_update["intermediate_steps"]), 1)
            action, obs = state_update["intermediate_steps"][0]
            self.assertIsNone(obs)
            self.assertIn("Thought.\nAction: abc", action.log)
            self.assertIn("action", action.tool_input)
            self.assertIn("action_input", action.tool_input)


@override_settings(IN_UNIT_TESTING=True)
class TestTaxonomyAgentPlannerToolsNode(ClickhouseTestMixin, APIBaseTest):
    def _get_node(self):
        class Node(TaxonomyAgentPlannerToolsNode):
            def run(self, state: AssistantState, config: RunnableConfig) -> AssistantState:
                toolkit = TestToolkit(self._team)
                return super()._run(state, toolkit, config=config)

        return Node(self.team)

    def test_node_handles_action_name_validation_error(self):
        state = {
            "intermediate_steps": [(AgentAction(tool="does not exist", tool_input="input", log="log"), "test")],
            "messages": [],
        }
        node = self._get_node()
        state_update = node.run(state, {})
        self.assertEqual(len(state_update["intermediate_steps"]), 1)
        action, observation = state_update["intermediate_steps"][0]
        self.assertIsNotNone(observation)
        self.assertIn("<pydantic_exception>", observation)

    def test_node_handles_action_input_validation_error(self):
        state = {
            "intermediate_steps": [
                (AgentAction(tool="retrieve_entity_property_values", tool_input="input", log="log"), "test")
            ],
            "messages": [],
        }
        node = self._get_node()
        state_update = node.run(state, {})
        self.assertEqual(len(state_update["intermediate_steps"]), 1)
        action, observation = state_update["intermediate_steps"][0]
        self.assertIsNotNone(observation)
        self.assertIn("<pydantic_exception>", observation)
