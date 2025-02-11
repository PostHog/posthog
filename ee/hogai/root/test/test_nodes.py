from unittest.mock import patch

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    HumanMessage as LangchainHumanMessage,
    ToolMessage as LangchainToolMessage,
)
from langchain_core.runnables import RunnableLambda
from parameterized import parameterized

from ee.hogai.root.nodes import RootNode, RootNodeTools
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantMessage, AssistantToolCall, AssistantToolCallMessage, HumanMessage
from posthog.test.base import BaseTest, ClickhouseTestMixin


class TestRootNode(ClickhouseTestMixin, BaseTest):
    def test_node_handles_plain_chat_response(self):
        with patch(
            "ee.hogai.root.nodes.RootNode._model",
            return_value=RunnableLambda(
                lambda _: LangchainAIMessage(content="Why did the chicken cross the road? To get to the other side!")
            ),
        ):
            node = RootNode(self.team)
            state_1 = AssistantState(messages=[HumanMessage(content="Tell me a joke")])
            next_state = node.run(state_1, {})
            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 1)
            self.assertIsInstance(next_state.messages[0], AssistantMessage)
            self.assertEqual(
                next_state.messages[0].content, "Why did the chicken cross the road? To get to the other side!"
            )

    @parameterized.expand(
        [
            ["trends"],
            ["funnel"],
            ["retention"],
        ]
    )
    def test_node_handles_insight_tool_call(self, insight_type):
        with patch(
            "ee.hogai.root.nodes.RootNode._model",
            return_value=RunnableLambda(
                lambda _: LangchainAIMessage(
                    content="Hang tight while I check this.",
                    tool_calls=[
                        {
                            "id": "xyz",
                            "name": "retrieve_data_for_question",
                            "args": {"query_description": "Foobar", "query_kind": insight_type},
                        }
                    ],
                )
            ),
        ):
            node = RootNode(self.team)
            state_1 = AssistantState(messages=[HumanMessage(content=f"generate {insight_type}")])
            next_state = node.run(state_1, {})
            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 1)
            assistant_message = next_state.messages[0]
            self.assertIsInstance(assistant_message, AssistantMessage)
            self.assertEqual(assistant_message.content, "Hang tight while I check this.")
            self.assertIsNotNone(assistant_message.id)
            self.assertEqual(len(assistant_message.tool_calls), 1)
            self.assertEqual(
                assistant_message.tool_calls[0],
                AssistantToolCall(
                    id="xyz",
                    name="retrieve_data_for_question",
                    args={"query_description": "Foobar", "query_kind": insight_type},
                ),
            )

    @parameterized.expand(
        [
            ["trends"],
            ["funnel"],
            ["retention"],
        ]
    )
    def test_node_handles_insight_tool_call_without_message(self, insight_type):
        with patch(
            "ee.hogai.root.nodes.RootNode._model",
            return_value=RunnableLambda(
                lambda _: LangchainAIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "xyz",
                            "name": "retrieve_data_for_question",
                            "args": {"query_description": "Foobar", "query_kind": insight_type},
                        }
                    ],
                )
            ),
        ):
            node = RootNode(self.team)
            state_1 = AssistantState(messages=[HumanMessage(content=f"generate {insight_type}")])
            next_state = node.run(state_1, {})
            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 1)
            assistant_message = next_state.messages[0]
            self.assertIsInstance(assistant_message, AssistantMessage)
            self.assertEqual(assistant_message.content, "")
            self.assertIsNotNone(assistant_message.id)
            self.assertEqual(len(assistant_message.tool_calls), 1)
            self.assertEqual(
                assistant_message.tool_calls[0],
                AssistantToolCall(
                    id="xyz",
                    name="retrieve_data_for_question",
                    args={"query_description": "Foobar", "query_kind": insight_type},
                ),
            )

    def test_node_reconstructs_conversation(self):
        node = RootNode(self.team)
        state_1 = AssistantState(messages=[HumanMessage(content="Hello")])
        self.assertEqual(node._construct_messages(state_1), [LangchainHumanMessage(content="Hello")])

        # We want full access to message history in root
        state_2 = AssistantState(
            messages=[
                HumanMessage(content="Hello"),
                AssistantMessage(content="Welcome!"),
                HumanMessage(content="Generate trends"),
            ]
        )
        self.assertEqual(
            node._construct_messages(state_2),
            [
                LangchainHumanMessage(content="Hello"),
                LangchainAIMessage(content="Welcome!"),
                LangchainHumanMessage(content="Generate trends"),
            ],
        )

    def test_node_reconstructs_conversation_with_tool_calls(self):
        node = RootNode(self.team)
        state = AssistantState(
            messages=[
                HumanMessage(content="Hello"),
                AssistantMessage(
                    content="Welcome!",
                    tool_calls=[
                        {
                            "id": "xyz",
                            "name": "retrieve_data_for_question",
                            "args": {},
                        }
                    ],
                ),
                AssistantMessage(content="Follow-up"),
                HumanMessage(content="Answer"),
                AssistantToolCallMessage(content="Answer", tool_call_id="xyz"),
            ]
        )
        self.assertEqual(
            node._construct_messages(state),
            [
                LangchainHumanMessage(content="Hello"),
                LangchainAIMessage(
                    content="Welcome!",
                    tool_calls=[
                        {
                            "id": "xyz",
                            "name": "retrieve_data_for_question",
                            "args": {},
                        }
                    ],
                ),
                LangchainToolMessage(content="Answer", tool_call_id="xyz"),
                LangchainAIMessage(content="Follow-up"),
                LangchainHumanMessage(content="Answer"),
            ],
        )


class TestRootNodeTools(BaseTest):
    def test_node_tools_router(self):
        node = RootNodeTools(self.team)

        # Test case 1: Last message is AssistantToolCallMessage - should return "root"
        state_1 = AssistantState(
            messages=[
                HumanMessage(content="Hello"),
                AssistantToolCallMessage(content="Tool result", tool_call_id="xyz"),
            ]
        )
        self.assertEqual(node.router(state_1), "root")

        # Test case 2: Has root tool call with query_kind - should return that query_kind
        state_2 = AssistantState(
            messages=[AssistantMessage(content="Hello")],
            root_tool_call_id="xyz",
            root_tool_insight_plan="Foobar",
            root_tool_insight_type="trends",
        )
        self.assertEqual(node.router(state_2), "trends")

        # Test case 3: No tool call message or root tool call - should return "end"
        state_3 = AssistantState(messages=[AssistantMessage(content="Hello")])
        self.assertEqual(node.router(state_3), "end")

    def test_run_no_assistant_message(self):
        node = RootNodeTools(self.team)
        state = AssistantState(messages=[HumanMessage(content="Hello")])
        self.assertIsNone(node.run(state, {}))

    def test_run_assistant_message_no_tool_calls(self):
        node = RootNodeTools(self.team)
        state = AssistantState(messages=[AssistantMessage(content="Hello")])
        self.assertIsNone(node.run(state, {}))

    def test_run_validation_error(self):
        node = RootNodeTools(self.team)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Hello",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name="retrieve_data_for_question",
                            args={"invalid_field": "should fail validation"},
                        )
                    ],
                )
            ]
        )
        result = node.run(state, {})
        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(len(result.messages), 1)
        self.assertIsInstance(result.messages[0], AssistantToolCallMessage)
        self.assertEqual(result.messages[0].tool_call_id, "test-id")
        self.assertIn("field required", result.messages[0].content.lower())

    def test_run_valid_tool_call(self):
        node = RootNodeTools(self.team)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Hello",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name="retrieve_data_for_question",
                            args={"query_kind": "trends", "query_description": "test query"},
                        )
                    ],
                )
            ]
        )
        result = node.run(state, {})
        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(result.root_tool_call_id, "xyz")
        self.assertEqual(result.root_tool_insight_plan, "test query")
        self.assertEqual(result.root_tool_insight_type, "trends")

    def test_run_multiple_tool_calls_raises(self):
        node = RootNodeTools(self.team)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Hello",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz1",
                            name="retrieve_data_for_question",
                            args={"query_kind": "trends", "query_description": "test query 1"},
                        ),
                        AssistantToolCall(
                            id="xyz2",
                            name="retrieve_data_for_question",
                            args={"query_kind": "funnel", "query_description": "test query 2"},
                        ),
                    ],
                )
            ]
        )
        with self.assertRaises(ValueError) as cm:
            node.run(state, {})
        self.assertEqual(str(cm.exception), "Expected exactly one tool call.")
