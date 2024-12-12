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
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.models import GroupTypeMapping
from posthog.schema import (
    AssistantMessage,
    AssistantTrendsQuery,
    FailureMessage,
    HumanMessage,
    RouterMessage,
    VisualizationMessage,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person


class DummyToolkit(TaxonomyAgentToolkit):
    def _get_tools(self) -> list[ToolkitTool]:
        return self._default_tools


@override_settings(IN_UNIT_TESTING=True)
class TestTaxonomyAgentPlannerNode(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.schema = AssistantTrendsQuery(series=[])

    def _get_node(self):
        class Node(TaxonomyAgentPlannerNode):
            def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
                prompt: ChatPromptTemplate = ChatPromptTemplate.from_messages([("user", "test")])
                toolkit = DummyToolkit(self._team)
                return super()._run_with_prompt_and_toolkit(state, prompt, toolkit, config=config)

        return Node(self.team)

    def test_agent_reconstructs_conversation(self):
        node = self._get_node()
        history = node._construct_messages(AssistantState(messages=[HumanMessage(content="Text")]))
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Text", history[0].content)
        self.assertNotIn(f"{{question}}", history[0].content)

        history = node._construct_messages(
            AssistantState(
                messages=[
                    HumanMessage(content="Text", id="0"),
                    VisualizationMessage(answer=self.schema, plan="randomplan", id="1", initiator="0"),
                ],
                start_id="1",
            )
        )
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Text", history[0].content)
        self.assertNotIn("{{question}}", history[0].content)
        self.assertEqual(history[1].type, "ai")
        self.assertEqual(history[1].content, "randomplan")

        history = node._construct_messages(
            AssistantState(
                messages=[
                    HumanMessage(content="Text", id="0"),
                    VisualizationMessage(answer=self.schema, plan="randomplan", id="1", initiator="0"),
                    HumanMessage(content="Text", id="2"),
                ],
                start_id="2",
            )
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
        history = node._construct_messages(
            AssistantState(
                messages=[
                    HumanMessage(content="Text", id="0"),
                    RouterMessage(content="trends", id="1"),
                    AssistantMessage(content="test", id="2"),
                ],
                start_id="0",
            )
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Text", history[0].content)
        self.assertNotIn("{{question}}", history[0].content)

    def test_agent_reconstructs_conversation_with_failures(self):
        node = self._get_node()
        history = node._construct_messages(
            AssistantState(
                messages=[
                    HumanMessage(content="Text"),
                    FailureMessage(content="Error"),
                    HumanMessage(content="Text"),
                ],
            )
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Text", history[0].content)
        self.assertNotIn("{{question}}", history[0].content)

    def test_agent_reconstructs_typical_conversation(self):
        node = self._get_node()
        history = node._construct_messages(
            AssistantState(
                messages=[
                    HumanMessage(content="Question 1", id="0"),
                    RouterMessage(content="trends", id="1"),
                    VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="Plan 1", id="2", initiator="0"),
                    AssistantMessage(content="Summary 1", id="3"),
                    HumanMessage(content="Question 2", id="4"),
                    RouterMessage(content="funnel", id="5"),
                    AssistantMessage(content="Loop 1", id="6"),
                    HumanMessage(content="Loop Answer 1", id="7"),
                    VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="Plan 2", id="8", initiator="4"),
                    AssistantMessage(content="Summary 2", id="9"),
                    HumanMessage(content="Question 3", id="10"),
                    RouterMessage(content="funnel", id="11"),
                ],
                start_id="10",
            )
        )
        self.assertEqual(len(history), 9)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Question 1", history[0].content)
        self.assertEqual(history[1].type, "ai")
        self.assertEqual(history[1].content, "Plan 1")
        self.assertEqual(history[2].type, "ai")
        self.assertEqual(history[2].content, "Summary 1")
        self.assertEqual(history[3].type, "human")
        self.assertIn("Question 2", history[3].content)
        self.assertEqual(history[4].type, "ai")
        self.assertEqual(history[4].content, "Loop 1")
        self.assertEqual(history[5].type, "human")
        self.assertEqual(history[5].content, "Loop Answer 1")
        self.assertEqual(history[6].content, "Plan 2")
        self.assertEqual(history[6].type, "ai")
        self.assertEqual(history[7].type, "ai")
        self.assertEqual(history[7].content, "Summary 2")
        self.assertEqual(history[8].type, "human")
        self.assertIn("Question 3", history[8].content)

    def test_agent_reconstructs_conversation_without_messages_after_parent(self):
        node = self._get_node()
        history = node._construct_messages(
            AssistantState(
                messages=[
                    HumanMessage(content="Question 1", id="0"),
                    RouterMessage(content="trends", id="1"),
                    AssistantMessage(content="Loop 1", id="2"),
                    HumanMessage(content="Loop Answer 1", id="3"),
                ],
                start_id="0",
            )
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Question 1", history[0].content)

    def test_agent_filters_out_low_count_events(self):
        _create_person(distinct_ids=["test"], team=self.team)
        for i in range(26):
            _create_event(event=f"event{i}", distinct_id="test", team=self.team)
            _create_event(event="distinctevent", distinct_id="test", team=self.team)
        node = self._get_node()
        self.assertEqual(
            node._events_prompt,
            "<defined_events><event><name>All Events</name><description>All events. This is a wildcard that matches all events.</description></event><event><name>distinctevent</name></event></defined_events>",
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
            state_update = node.run(AssistantState(messages=[HumanMessage(content="Question")]), {})
            self.assertEqual(len(state_update.intermediate_steps), 1)
            action, obs = state_update.intermediate_steps[0]
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
            state_update = node.run(AssistantState(messages=[HumanMessage(content="Question")]), {})
            self.assertEqual(len(state_update.intermediate_steps), 1)
            action, obs = state_update.intermediate_steps[0]
            self.assertIsNone(obs)
            self.assertIn("Thought.\nAction: abc", action.log)
            self.assertIn("action", action.tool_input)
            self.assertIn("action_input", action.tool_input)

    def test_node_outputs_all_events_prompt(self):
        node = self._get_node()
        self.assertIn("All Events", node._events_prompt)
        self.assertIn(
            "<event><name>All Events</name><description>All events. This is a wildcard that matches all events.</description></event>",
            node._events_prompt,
        )

    def test_format_prompt(self):
        node = self._get_node()
        self.assertNotIn("Human:", node._get_react_format_prompt(DummyToolkit(self.team)))
        self.assertIn("retrieve_event_properties,", node._get_react_format_prompt(DummyToolkit(self.team)))
        self.assertIn(
            "retrieve_event_properties(event_name: str)", node._get_react_format_prompt(DummyToolkit(self.team))
        )

    def test_property_filters_prompt(self):
        GroupTypeMapping.objects.create(team=self.team, project=self.project, group_type="org", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, project=self.project, group_type="account", group_type_index=1)
        node = self._get_node()
        prompt = node._get_react_property_filters_prompt()
        self.assertIn("org, account.", prompt)


@override_settings(IN_UNIT_TESTING=True)
class TestTaxonomyAgentPlannerToolsNode(ClickhouseTestMixin, APIBaseTest):
    def _get_node(self):
        class Node(TaxonomyAgentPlannerToolsNode):
            def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
                toolkit = DummyToolkit(self._team)
                return super()._run_with_toolkit(state, toolkit, config=config)

        return Node(self.team)

    def test_node_handles_action_name_validation_error(self):
        state = AssistantState(
            intermediate_steps=[(AgentAction(tool="does not exist", tool_input="input", log="log"), "test")],
            messages=[],
        )
        node = self._get_node()
        state_update = node.run(state, {})
        self.assertEqual(len(state_update.intermediate_steps), 1)
        action, observation = state_update.intermediate_steps[0]
        self.assertIsNotNone(observation)
        self.assertIn("<pydantic_exception>", observation)

    def test_node_handles_action_input_validation_error(self):
        state = AssistantState(
            intermediate_steps=[
                (AgentAction(tool="retrieve_entity_property_values", tool_input="input", log="log"), "test")
            ],
            messages=[],
        )
        node = self._get_node()
        state_update = node.run(state, {})
        self.assertEqual(len(state_update.intermediate_steps), 1)
        action, observation = state_update.intermediate_steps[0]
        self.assertIsNotNone(observation)
        self.assertIn("<pydantic_exception>", observation)
