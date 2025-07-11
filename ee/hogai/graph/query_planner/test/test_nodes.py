from django.test import override_settings
from langchain_core.agents import AgentAction
from langchain_core.prompts import HumanMessagePromptTemplate, AIMessagePromptTemplate

from ee.hogai.graph.query_planner.nodes import QueryPlannerNode, QueryPlannerToolsNode
from ee.hogai.graph.query_planner.toolkit import TaxonomyAgentToolkit
from ee.hogai.utils.types import AssistantState
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
from unittest.mock import patch


class DummyToolkit(TaxonomyAgentToolkit):
    pass


@override_settings(IN_UNIT_TESTING=True)
class TestQueryPlannerNode(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.schema = AssistantTrendsQuery(series=[])

    def _get_node(self):
        return QueryPlannerNode(self.team, self.user)

    def test_agent_reconstructs_conversation(self):
        node = self._get_node()
        history = node._construct_messages(
            AssistantState(messages=[HumanMessage(content="Message")], root_tool_insight_plan="Text")
        )
        self.assertEqual(len(history), 2)
        self.assertIsInstance(history[1], HumanMessagePromptTemplate)
        self.assertIn("Text", history[1].prompt.template)
        self.assertNotIn(f"{{question}}", history[1].prompt.template)

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
        self.assertEqual(len(history), 2)
        self.assertIsInstance(history[1], HumanMessagePromptTemplate)
        self.assertIn("Question", history[1].prompt.template)
        self.assertNotIn("{{question}}", history[1].prompt.template)

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
        self.assertEqual(len(history), 2)
        self.assertIsInstance(history[1], HumanMessagePromptTemplate)
        self.assertIn("Question", history[1].prompt.template)
        self.assertNotIn("{{question}}", history[1].prompt.template)

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
        self.assertEqual(len(history), 6, history)
        self.assertIsInstance(history[1], HumanMessagePromptTemplate)
        self.assertIn("Question 1", history[1].prompt.template)
        self.assertIsInstance(history[2], AIMessagePromptTemplate)
        self.assertEqual(history[2].prompt.template, "Plan 1")
        self.assertIsInstance(history[3], HumanMessagePromptTemplate)
        self.assertIn("Question 2", history[3].prompt.template)
        self.assertIsInstance(history[4], AIMessagePromptTemplate)
        self.assertEqual(history[4].prompt.template, "Plan 2")
        self.assertIsInstance(history[5], HumanMessagePromptTemplate)
        self.assertIn("Question 3", history[5].prompt.template)

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

    # Removed test_agent_handles_output_without_tool_call as this functionality
    # is now handled differently and the test was testing legacy behavior

    def test_node_outputs_all_events_prompt(self):
        node = self._get_node()
        self.assertIn("All events", node._format_events_prompt([]))
        self.assertIn(
            "<event><name>All events</name><description>All events. This is a wildcard that matches all events.</description></event>",
            node._format_events_prompt([]),
        )

    # Removed test_format_prompt as _get_react_format_prompt method no longer exists
    # The current implementation uses a different approach for prompt formatting

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
        self.assertEqual(len(history), 2)  # system prompts + human message
        self.assertIsInstance(history[1], HumanMessagePromptTemplate)
        self.assertIn("Foobar", history[1].prompt.template)
        self.assertNotIn("{{question}}", history[1].prompt.template)

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
        # - system prompt
        # - 10 pairs of human/ai messages from the last 10 visualization messages (20 total)
        # - 1 final human message with root_tool_insight_plan
        self.assertEqual(len(history), 22, history)

        # Check that we only got the last 10 visualization messages
        for i in range(1, 11):
            # The human messages should contain the questions from the last 10 visualization messages
            human_msg = history[i * 2 - 1]
            self.assertIsInstance(human_msg, HumanMessagePromptTemplate)
            self.assertIn(f"Question {i + 4}", human_msg.prompt.template)

            # The AI messages should contain the plans from the last 10 visualization messages
            ai_msg = history[i * 2]
            self.assertIsInstance(ai_msg, AIMessagePromptTemplate)
            self.assertEqual(ai_msg.prompt.template, f"Plan {i + 4}")

        # Check the final message contains the root_tool_insight_plan
        final_msg = history[-1]
        self.assertIsInstance(final_msg, HumanMessagePromptTemplate)
        self.assertIn("Final Question", final_msg.prompt.template)

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
        with patch("ee.hogai.graph.query_planner.nodes.CORE_FILTER_DEFINITIONS_BY_GROUP") as mock_definitions:
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

        with patch("ee.hogai.graph.query_planner.nodes.CORE_FILTER_DEFINITIONS_BY_GROUP") as mock_definitions:
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
        return QueryPlannerToolsNode(self.team, self.user)

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

    def test_node_handles_action_input_validation_error_string(self):
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

    def test_node_handles_action_input_validation_error_dict(self):
        state = AssistantState(
            intermediate_steps=[
                (
                    AgentAction(
                        tool="retrieve_entity_property_values",
                        tool_input={
                            "foo_name": "bar",
                        },
                        log="log",
                    ),
                    "test",
                )
            ],
            messages=[],
        )
        node = self._get_node()
        state_update = node.run(state, {})
        self.assertEqual(len(state_update.intermediate_steps), 1)
        action, observation = state_update.intermediate_steps[0]
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
                AssistantState(
                    messages=[HumanMessage(content="Question")],
                    root_tool_call_id="1",
                    root_tool_insight_type="sql",
                    plan="plan",
                ),
            ),
            "sql",
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
        intermediate_steps = [
            (
                AgentAction(
                    tool="retrieve_event_properties",
                    tool_input={
                        "event_name": "event",
                    },
                    log=f"log_{i}",
                ),
                "observation",
            )
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
        intermediate_steps = [
            (
                AgentAction(
                    tool="retrieve_event_properties",
                    tool_input={
                        "event_name": "event",
                    },
                    log=f"log_{i}",
                ),
                "observation",
            )
            for i in range(15)
        ]
        intermediate_steps.append(
            (
                AgentAction(
                    tool="final_answer",
                    tool_input={"query_kind": "trends", "plan": "This is the final plan"},
                    log="final",
                ),
                None,
            )
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
        intermediate_steps = [
            (
                AgentAction(
                    tool="retrieve_event_properties",
                    tool_input={
                        "event_name": "event",
                    },
                    log=f"log_{i}",
                ),
                "observation",
            )
            for i in range(15)
        ]
        intermediate_steps.append(
            (
                AgentAction(
                    tool="ask_user_for_help",
                    tool_input={
                        "request": "Need help with this",
                    },
                    log="help",
                ),
                None,
            )
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
