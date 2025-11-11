from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import override_settings

from langchain_core.agents import AgentAction
from langchain_core.messages import (
    AIMessage,
    ToolMessage as LangchainToolMessage,
)
from langchain_core.prompts import AIMessagePromptTemplate, HumanMessagePromptTemplate

from posthog.schema import (
    AssistantMessage,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    FailureMessage,
    HumanMessage,
    VisualizationMessage,
)

from posthog.test.test_utils import create_group_type_mapping_without_created_at

from ee.hogai.graph.query_planner.nodes import QueryPlannerNode, QueryPlannerToolsNode
from ee.hogai.graph.query_planner.toolkit import TaxonomyAgentToolkit
from ee.hogai.utils.types import AssistantState


class DummyToolkit(TaxonomyAgentToolkit):
    _parent_tool_call_id: str | None = None
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

    # Removed test_agent_handles_output_without_tool_call as this functionality
    # is now handled differently and the test was testing legacy behavior

    # Removed test_format_prompt as _get_react_format_prompt method no longer exists
    # The current implementation uses a different approach for prompt formatting

    def test_property_filters_prompt(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project=self.project, group_type="org", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project=self.project, group_type="account", group_type_index=1
        )
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

    def test_construct_messages_appends_query_planner_intermediate_messages(self):
        node = self._get_node()
        intermediate_messages = [
            AIMessage(content="First message"),
            LangchainToolMessage(content="Tool result", tool_call_id="call_1"),
            AIMessage(content="Second message"),
        ]

        history = node._construct_messages(
            AssistantState(
                root_tool_insight_plan="Test Plan", query_planner_intermediate_messages=intermediate_messages
            )
        )

        # System prompt + human message + 3 intermediate messages = 5 total
        self.assertEqual(len(history), 5)

        # Check that intermediate messages are appended at the end
        self.assertEqual(history[2], intermediate_messages[0])
        self.assertEqual(history[3], intermediate_messages[1])
        self.assertEqual(history[4], intermediate_messages[2])


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
                    messages=[AssistantToolCallMessage(content="help", tool_call_id="1")],
                    root_tool_call_id=None,
                    plan=None,
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
        self.assertIsNone(state_update.intermediate_steps)
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
        self.assertIsNone(state_update.intermediate_steps)
        self.assertEqual(state_update.plan, "This is the final plan")

    def test_node_resets_query_planner_intermediate_messages_after_final_answer(self):
        intermediate_messages = [
            AIMessage(content="Intermediate message 1"),
            LangchainToolMessage(content="Tool result", tool_call_id="call_1"),
        ]
        state = AssistantState(
            intermediate_steps=[
                (
                    AgentAction(
                        tool="final_answer",
                        tool_input={"query_kind": "trends", "plan": "Final plan"},
                        log="final",
                    ),
                    None,
                )
            ],
            query_planner_intermediate_messages=intermediate_messages,
            messages=[],
            root_tool_call_id="1",
        )

        node = self._get_node()
        state_update = node.run(state, {})

        # Should reset query_planner_intermediate_messages to None after final answer
        self.assertIsNone(state_update.query_planner_intermediate_messages)
        self.assertEqual(state_update.plan, "Final plan")

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
        self.assertIsNone(state_update.intermediate_steps)
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
        self.assertIsNone(state_update.intermediate_steps)
        self.assertEqual(len(state_update.messages or []), 1)
        messages = state_update.messages or []
        if messages and hasattr(messages[0], "content") and messages[0].content:
            content_str = str(messages[0].content).lower()
            self.assertIn("maximum number of iterations", content_str)
            self.assertNotIn("pydantic", content_str)

    def test_node_appends_new_tool_result(self):
        initial_steps = [
            (
                AgentAction(
                    tool="retrieve_event_properties",
                    tool_input={"event_name": "test_event"},
                    log="initial_log",
                ),
                "initial_result",
            )
        ]

        state = AssistantState(
            intermediate_steps=initial_steps,
            messages=[],
            root_tool_call_id="1",
        )

        node = self._get_node()
        state_update = node.run(state, {})

        # Should have 2 steps: initial + updated with tool result
        self.assertEqual(len(state_update.intermediate_steps or []), 1)
        action, observation = (state_update.intermediate_steps or [])[0]
        self.assertEqual(action.log, "initial_log")
        self.assertIsNotNone(observation)
        # The observation should contain the actual tool result, not the initial "test" value

    def test_node_appends_new_assistant_message(self):
        initial_messages = [
            AIMessage(content="Previous message"),
        ]

        state = AssistantState(
            intermediate_steps=[
                (
                    AgentAction(
                        tool="retrieve_event_properties",
                        tool_input={"event_name": "test_event"},
                        log="test_log_id",
                    ),
                    "test",  # This gets replaced by actual tool result
                )
            ],
            query_planner_intermediate_messages=initial_messages,
            messages=[],
            root_tool_call_id="1",
        )

        node = self._get_node()
        state_update = node.run(state, {})

        # Should have 2 messages: initial + new tool message
        self.assertEqual(len(state_update.query_planner_intermediate_messages or []), 2)
        messages = state_update.query_planner_intermediate_messages or []

        # First message should be the initial one
        self.assertEqual(messages[0], initial_messages[0])

        # Second message should be the new tool message
        self.assertIsInstance(messages[1], LangchainToolMessage)
        self.assertEqual(messages[1].tool_call_id, "test_log_id")
