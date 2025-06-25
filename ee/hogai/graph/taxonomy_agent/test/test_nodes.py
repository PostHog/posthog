from unittest.mock import patch

from django.test import override_settings
from langchain_core.agents import AgentAction
from langchain_core.messages import AIMessage as LangchainAIMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda

from ee.hogai.graph.taxonomy_agent.nodes import (
    ChatPromptTemplate,
    TaxonomyAgentPlannerNode,
    TaxonomyAgentPlannerToolsNode,
)
from ee.hogai.graph.taxonomy_agent.toolkit import TaxonomyAgentToolkit, ToolkitTool
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.models import GroupTypeMapping
from posthog.schema import (
    AssistantMessage,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    MaxEventContext,
    FailureMessage,
    HumanMessage,
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

        return Node(self.team, self.user)

    def test_agent_reconstructs_conversation(self):
        node = self._get_node()
        history = node._construct_messages(
            AssistantState(messages=[HumanMessage(content="Message")], root_tool_insight_plan="Text")
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Text", history[0].content)
        self.assertNotIn(f"{{question}}", history[0].content)

    def test_agent_reconstructs_conversation_and_omits_unknown_messages(self):
        node = self._get_node()
        history = node._construct_messages(
            AssistantState(
                messages=[
                    HumanMessage(content="Text", id="0"),
                    AssistantMessage(content="test", id="2"),
                ],
                start_id="0",
                root_tool_insight_plan="Question",
            )
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Question", history[0].content)
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
                root_tool_insight_plan="Question",
            )
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Question", history[0].content)
        self.assertNotIn("{{question}}", history[0].content)

    def test_agent_reconstructs_typical_conversation(self):
        node = self._get_node()
        history = node._construct_messages(
            AssistantState(
                messages=[
                    HumanMessage(content="General Question 1", id="0"),
                    VisualizationMessage(
                        answer=AssistantTrendsQuery(series=[]), plan="Plan 1", id="2", initiator="0", query="Question 1"
                    ),
                    AssistantMessage(content="Summary 1", id="3"),
                    HumanMessage(content="General Question 2", id="4"),
                    AssistantToolCallMessage(content="funnel", id="5", tool_call_id="5"),
                    AssistantMessage(content="Loop 1", id="6"),
                    HumanMessage(content="Loop Answer 1", id="7"),
                    VisualizationMessage(
                        answer=AssistantTrendsQuery(series=[]), plan="Plan 2", id="8", initiator="4", query="Question 2"
                    ),
                    AssistantMessage(content="Summary 2", id="9"),
                    HumanMessage(content="General Question 3", id="10"),
                ],
                root_tool_insight_plan="Question 3",
            )
        )
        self.assertEqual(len(history), 5)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Question 1", history[0].content)
        self.assertEqual(history[1].type, "ai")
        self.assertEqual(history[1].content, "Plan 1")
        self.assertEqual(history[2].type, "human")
        self.assertIn("Question 2", history[2].content)
        self.assertEqual(history[3].type, "ai")
        self.assertEqual(history[3].content, "Plan 2")
        self.assertEqual(history[4].type, "human")
        self.assertIn("Question 3", history[4].content)

    def test_adds_format_reminder(self):
        node = self._get_node()
        history = node._construct_messages(
            AssistantState(messages=[HumanMessage(content="Message")], root_tool_insight_plan="Text")
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Reminder", history[0].content)

    def test_agent_filters_out_low_count_events(self):
        _create_person(distinct_ids=["test"], team=self.team)
        for i in range(26):
            _create_event(event=f"event{i}", distinct_id="test", team=self.team)
            _create_event(event="distinctevent", distinct_id="test", team=self.team)
        node = self._get_node()
        self.assertEqual(
            node._format_events_prompt([]),
            "<defined_events><event><name>All events</name><description>All events. This is a wildcard that matches all events.</description></event><event><name>distinctevent</name></event></defined_events>",
        )

    def test_agent_preserves_low_count_events_for_smaller_teams(self):
        _create_person(distinct_ids=["test"], team=self.team)
        _create_event(event="distinctevent", distinct_id="test", team=self.team)
        node = self._get_node()
        self.assertIn("distinctevent", node._format_events_prompt([]))
        self.assertIn("all events", node._format_events_prompt([]))

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
            "ee.hogai.graph.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model",
            return_value=RunnableLambda(lambda _: LangchainAIMessage(content="I don't want to output an action.")),
        ):
            node = self._get_node()
            state_update = node.run(AssistantState(messages=[HumanMessage(content="Question")]), {})
            self.assertEqual(len(state_update.intermediate_steps or []), 1)
            action, obs = (state_update.intermediate_steps or [])[0]
            self.assertIsNone(obs)
            self.assertIn("I don't want to output an action.", action.log)
            self.assertIn("Action:", action.log)
            self.assertIn("Action:", action.tool_input)

    def test_agent_handles_output_with_malformed_json(self):
        with patch(
            "ee.hogai.graph.taxonomy_agent.nodes.TaxonomyAgentPlannerNode._model",
            return_value=RunnableLambda(lambda _: LangchainAIMessage(content="Thought.\nAction: abc")),
        ):
            node = self._get_node()
            state_update = node.run(AssistantState(messages=[HumanMessage(content="Question")]), {})
            self.assertEqual(len(state_update.intermediate_steps or []), 1)
            action, obs = (state_update.intermediate_steps or [])[0]
            self.assertIsNone(obs)
            self.assertIn("Thought.\nAction: abc", action.log)
            self.assertIn("action", action.tool_input)
            self.assertIn("action_input", action.tool_input)

    def test_node_outputs_all_events_prompt(self):
        node = self._get_node()
        self.assertIn("All events", node._format_events_prompt([]))
        self.assertIn(
            "<event><name>All events</name><description>All events. This is a wildcard that matches all events.</description></event>",
            node._format_events_prompt([]),
        )

    def test_format_prompt(self):
        node = self._get_node()
        self.assertNotIn("Human:", node._get_react_format_prompt(DummyToolkit(self.team)))
        self.assertIn("retrieve_event_properties,", node._get_react_format_prompt(DummyToolkit(self.team)))

    def test_property_filters_prompt(self):
        GroupTypeMapping.objects.create(team=self.team, project=self.project, group_type="org", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, project=self.project, group_type="account", group_type_index=1)
        node = self._get_node()
        prompt = node._get_react_property_filters_prompt()
        self.assertIn("org, account.", prompt)

    def test_injects_insight_description(self):
        node = self._get_node()
        history = node._construct_messages(
            AssistantState(
                messages=[
                    HumanMessage(content="Text", id="0"),
                    AssistantMessage(content="test", id="2"),
                ],
                start_id="0",
                root_tool_insight_plan="Foobar",
                root_tool_insight_type="trends",
            )
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].type, "human")
        self.assertIn("Foobar", history[0].content)
        self.assertNotIn("{{question}}", history[0].content)

    def test_visualization_message_limit(self):
        # Create 15 visualization messages
        messages = []
        for i in range(15):
            messages.append(
                VisualizationMessage(
                    answer=AssistantTrendsQuery(series=[]),
                    plan=f"Plan {i}",
                    id=str(i),
                    initiator=str(i),
                    query=f"Question {i}",
                )
            )

        node = self._get_node()
        history = node._construct_messages(AssistantState(messages=messages, root_tool_insight_plan="Final Question"))

        # We expect 21 messages in total:
        # - 10 pairs of human/ai messages from the last 10 visualization messages (20 total)
        # - 1 final human message with root_tool_insight_plan
        self.assertEqual(len(history), 21)

        # Check that we only got the last 10 visualization messages
        for i in range(10):
            # The human messages should contain the questions from the last 10 visualization messages
            human_msg = history[i * 2]
            self.assertEqual(human_msg.type, "human")
            self.assertIn(f"Question {i + 5}", human_msg.content)

            # The AI messages should contain the plans from the last 10 visualization messages
            ai_msg = history[i * 2 + 1]
            self.assertEqual(ai_msg.type, "ai")
            self.assertEqual(ai_msg.content, f"Plan {i + 5}")

        # Check the final message contains the root_tool_insight_plan
        final_msg = history[-1]
        self.assertEqual(final_msg.type, "human")
        self.assertIn("Final Question", final_msg.content)

    def test_events_in_context_adds_events_to_prompt(self):
        """Test that events from context are added to the events list"""
        _create_person(distinct_ids=["test"], team=self.team)
        _create_event(event="existing_event", distinct_id="test", team=self.team)

        node = self._get_node()
        events_in_context = [
            MaxEventContext(id="1", name="context_event", description="Event from context"),
            MaxEventContext(id="2", name="another_context_event", description=None),
        ]

        prompt = node._format_events_prompt(events_in_context)

        self.assertIn("context_event", prompt)
        self.assertIn("another_context_event", prompt)
        self.assertIn("Event from context", prompt)

    def test_events_in_context_overwrites_system_event_filtering(self):
        """Test that system events are not filtered out if they're in context"""
        node = self._get_node()

        # Test with a system event that would normally be filtered
        # (we'll mock the core filter definitions to include a system event)
        with patch("ee.hogai.graph.taxonomy_agent.nodes.CORE_FILTER_DEFINITIONS_BY_GROUP") as mock_definitions:
            mock_definitions.__getitem__.return_value = {
                "test_system_event": {
                    "system": True,
                    "description": "System event that should be filtered",
                    "ignored_in_assistant": True,
                }
            }

            events_in_context = [
                MaxEventContext(id="1", name="test_system_event", description="System event from context"),
            ]

            prompt = node._format_events_prompt(events_in_context)

            # Should include the system event because it's in context
            self.assertIn("test_system_event", prompt)

    def test_events_in_context_duplicates_are_handled(self):
        """Test that duplicate events between context and taxonomy are handled correctly"""
        _create_person(distinct_ids=["test"], team=self.team)
        _create_event(event="duplicate_event", distinct_id="test", team=self.team)

        node = self._get_node()
        events_in_context = [
            MaxEventContext(id="1", name="duplicate_event", description="Context description"),
        ]

        prompt = node._format_events_prompt(events_in_context)

        # Should only appear once in the prompt
        event_count = prompt.count("<name>duplicate_event</name>")
        self.assertEqual(event_count, 1)

    def test_events_in_context_mixed_with_core_definitions(self):
        """Test events from context mixed with core event definitions"""
        node = self._get_node()

        with patch("ee.hogai.graph.taxonomy_agent.nodes.CORE_FILTER_DEFINITIONS_BY_GROUP") as mock_definitions:
            mock_definitions.__getitem__.return_value = {
                "core_event": {
                    "description": "Core event description",
                    "label": "Core Event",
                }
            }

            events_in_context = [
                MaxEventContext(id="1", name="core_event", description="Context description"),
                MaxEventContext(id="2", name="context_only_event", description="Only in context"),
            ]

            prompt = node._format_events_prompt(events_in_context)

            # Should include both events
            self.assertIn("core_event", prompt)
            self.assertIn("context_only_event", prompt)

            # For core_event, should use core definition, not context description
            # because core definitions take precedence
            self.assertIn("Core Event. Core event description", prompt)
            self.assertNotIn("Context description", prompt)

            # For context-only event, should use context description
            self.assertIn("Only in context", prompt)


@override_settings(IN_UNIT_TESTING=True)
class TestTaxonomyAgentPlannerToolsNode(ClickhouseTestMixin, APIBaseTest):
    def _get_node(self):
        class Node(TaxonomyAgentPlannerToolsNode):
            def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
                toolkit = DummyToolkit(self._team)
                return super()._run_with_toolkit(state, toolkit, config=config)

        return Node(self.team, self.user)

    def test_node_handles_action_name_validation_error(self):
        state = AssistantState(
            intermediate_steps=[(AgentAction(tool="does not exist", tool_input="input", log="log"), "test")],
            messages=[],
        )
        node = self._get_node()
        state_update = node.run(state, {})
        self.assertEqual(len(state_update.intermediate_steps or []), 1)
        action, observation = (state_update.intermediate_steps or [])[0]
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
        self.assertEqual(len(state_update.intermediate_steps or []), 1)
        action, observation = (state_update.intermediate_steps or [])[0]
        self.assertIsNotNone(observation)
        self.assertIn("<pydantic_exception>", observation)

    def test_router(self):
        node = self._get_node()
        self.assertEqual(
            node.router(
                AssistantState(messages=[HumanMessage(content="Question")], root_tool_call_id="1"),
            ),
            "continue",
        )
        self.assertEqual(
            node.router(
                AssistantState(messages=[HumanMessage(content="Question")], root_tool_call_id="1", plan=""),
            ),
            "continue",
        )
        self.assertEqual(
            node.router(
                AssistantState(messages=[HumanMessage(content="Question")], root_tool_call_id="1", plan="plan"),
            ),
            "plan_found",
        )
        self.assertEqual(
            node.router(
                AssistantState(
                    messages=[AssistantToolCallMessage(content="help", tool_call_id="1")], root_tool_call_id="", plan=""
                ),
            ),
            "end",
        )

    def test_node_terminates_after_max_iterations(self):
        # Create state with 16 intermediate steps
        intermediate_steps: list[tuple[AgentAction, str | None]] = [
            (AgentAction(tool="retrieve_event_properties", tool_input="input", log=f"log_{i}"), "observation")
            for i in range(16)
        ]
        state = AssistantState(
            intermediate_steps=intermediate_steps,
            messages=[],
            root_tool_call_id="1",
        )

        node = self._get_node()
        state_update = node.run(state, {})

        # Should reset state and return message about reaching limit
        self.assertEqual(len(state_update.intermediate_steps or []), 0)
        self.assertEqual(len(state_update.messages or []), 1)
        messages = state_update.messages or []
        if messages and hasattr(messages[0], "content") and messages[0].content:
            self.assertIn("maximum number of iterations", str(messages[0].content).lower())

    def test_node_allows_final_answer_at_max_iterations(self):
        # Create state with 16 intermediate steps, last one being final_answer
        intermediate_steps: list[tuple[AgentAction, str | None]] = [
            (AgentAction(tool="retrieve_event_properties", tool_input="input", log=f"log_{i}"), "observation")
            for i in range(15)
        ]
        intermediate_steps.append(
            (AgentAction(tool="final_answer", tool_input="This is the final plan", log="final"), None)
        )

        state = AssistantState(
            intermediate_steps=intermediate_steps,
            messages=[],
            root_tool_call_id="1",
        )

        node = self._get_node()
        state_update = node.run(state, {})

        # Should accept the final answer even at max iterations
        self.assertEqual(len(state_update.intermediate_steps or []), 0)
        self.assertEqual(state_update.plan, "This is the final plan")

    def test_node_allows_help_request_at_max_iterations(self):
        # Create state with 16 intermediate steps, last one being ask_user_for_help
        intermediate_steps: list[tuple[AgentAction, str | None]] = [
            (AgentAction(tool="retrieve_event_properties", tool_input="input", log=f"log_{i}"), "observation")
            for i in range(15)
        ]
        intermediate_steps.append(
            (AgentAction(tool="ask_user_for_help", tool_input="Need help with this", log="help"), None)
        )

        state = AssistantState(
            intermediate_steps=intermediate_steps,
            messages=[],
            root_tool_call_id="1",
        )

        node = self._get_node()
        state_update = node.run(state, {})

        # Should accept the help request even at max iterations
        self.assertEqual(len(state_update.intermediate_steps or []), 0)
        self.assertEqual(len(state_update.messages or []), 1)
        messages = state_update.messages or []
        if messages and hasattr(messages[0], "content") and messages[0].content:
            self.assertIn("need help with this", str(messages[0].content).lower())

    def test_node_prioritizes_max_iterations_over_validation_error(self):
        # Create state with 16 intermediate steps, last one causing validation error
        intermediate_steps: list[tuple[AgentAction, str | None]] = [
            (AgentAction(tool="retrieve_event_properties", tool_input="input", log=f"log_{i}"), "observation")
            for i in range(15)
        ]
        intermediate_steps.append((AgentAction(tool="invalid_tool", tool_input="bad input", log="error"), None))

        state = AssistantState(
            intermediate_steps=intermediate_steps,
            messages=[],
            root_tool_call_id="1",
        )

        node = self._get_node()
        state_update = node.run(state, {})

        # Should return max iterations message instead of validation error
        self.assertEqual(len(state_update.intermediate_steps or []), 0)
        self.assertEqual(len(state_update.messages or []), 1)
        messages = state_update.messages or []
        if messages and hasattr(messages[0], "content") and messages[0].content:
            content_str = str(messages[0].content).lower()
            self.assertIn("maximum number of iterations", content_str)
            self.assertNotIn("pydantic", content_str)
