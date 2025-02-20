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
            "ee.hogai.root.nodes.RootNode._get_model",
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
            "ee.hogai.root.nodes.RootNode._get_model",
            return_value=RunnableLambda(
                lambda _: LangchainAIMessage(
                    content="Hang tight while I check this.",
                    tool_calls=[
                        {
                            "id": "xyz",
                            "name": "create_and_query_insight",
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
                    name="create_and_query_insight",
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
            "ee.hogai.root.nodes.RootNode._get_model",
            return_value=RunnableLambda(
                lambda _: LangchainAIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "xyz",
                            "name": "create_and_query_insight",
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
                    name="create_and_query_insight",
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
                            "name": "create_and_query_insight",
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
                            "name": "create_and_query_insight",
                            "args": {},
                        }
                    ],
                ),
                LangchainToolMessage(content="Answer", tool_call_id="xyz"),
                LangchainAIMessage(content="Follow-up"),
                LangchainHumanMessage(content="Answer"),
            ],
        )

    def test_node_filters_tool_calls_without_responses(self):
        node = RootNode(self.team)
        state = AssistantState(
            messages=[
                HumanMessage(content="Hello"),
                AssistantMessage(
                    content="Welcome!",
                    tool_calls=[
                        # This tool call has a response
                        {
                            "id": "xyz1",
                            "name": "create_and_query_insight",
                            "args": {},
                        },
                        # This tool call has no response and should be filtered out
                        {
                            "id": "xyz2",
                            "name": "create_and_query_insight",
                            "args": {},
                        },
                    ],
                ),
                AssistantToolCallMessage(content="Answer for xyz1", tool_call_id="xyz1"),
            ]
        )
        messages = node._construct_messages(state)

        # Verify we get exactly 3 messages
        self.assertEqual(len(messages), 3)

        # Verify the messages are in correct order and format
        self.assertEqual(messages[0], LangchainHumanMessage(content="Hello"))

        # Verify the assistant message only includes the tool call that has a response
        assistant_message = messages[1]
        self.assertIsInstance(assistant_message, LangchainAIMessage)
        self.assertEqual(assistant_message.content, "Welcome!")
        self.assertEqual(len(assistant_message.tool_calls), 1)
        self.assertEqual(assistant_message.tool_calls[0]["id"], "xyz1")

        # Verify the tool response is included
        tool_message = messages[2]
        self.assertIsInstance(tool_message, LangchainToolMessage)
        self.assertEqual(tool_message.content, "Answer for xyz1")
        self.assertEqual(tool_message.tool_call_id, "xyz1")

    def test_hard_limit_removes_tools(self):
        with patch(
            "ee.hogai.root.nodes.ChatOpenAI",
            return_value=RunnableLambda(lambda _: LangchainAIMessage(content="I can't help with that anymore.")),
        ):
            node = RootNode(self.team)

            # Create a state that has hit the hard limit (4 tool calls)
            state = AssistantState(messages=[HumanMessage(content="Hello")], root_tool_calls_count=4)

            # Run the node
            next_state = node.run(state, {})

            # Verify the response doesn't contain any tool calls
            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 1)
            message = next_state.messages[0]
            self.assertIsInstance(message, AssistantMessage)
            self.assertEqual(message.content, "I can't help with that anymore.")
            self.assertEqual(message.tool_calls, [])

            # Verify the hard limit message was added to the conversation
            messages = node._construct_messages(state)
            self.assertIn("iterations", messages[-1].content)


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
        self.assertEqual(node.run(state, {}), PartialAssistantState(root_tool_calls_count=0))

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
                            name="create_and_query_insight",
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
                            name="create_and_query_insight",
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
                            name="create_and_query_insight",
                            args={"query_kind": "trends", "query_description": "test query 1"},
                        ),
                        AssistantToolCall(
                            id="xyz2",
                            name="create_and_query_insight",
                            args={"query_kind": "funnel", "query_description": "test query 2"},
                        ),
                    ],
                )
            ]
        )
        with self.assertRaises(ValueError) as cm:
            node.run(state, {})
        self.assertEqual(str(cm.exception), "Expected exactly one tool call.")

    def test_run_increments_tool_count(self):
        node = RootNodeTools(self.team)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Hello",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name="create_and_query_insight",
                            args={"query_kind": "trends", "query_description": "test query"},
                        )
                    ],
                )
            ],
            root_tool_calls_count=2,  # Starting count
        )
        result = node.run(state, {})
        self.assertEqual(result.root_tool_calls_count, 3)  # Should increment by 1

        # Test increment also happens on validation error
        state_with_error = AssistantState(
            messages=[
                AssistantMessage(
                    content="Hello",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name="create_and_query_insight",
                            args={"invalid_field": "should fail validation"},
                        )
                    ],
                )
            ],
            root_tool_calls_count=1,
        )
        result = node.run(state_with_error, {})
        self.assertEqual(result.root_tool_calls_count, 2)

    def test_run_resets_tool_count(self):
        node = RootNodeTools(self.team)

        # Test reset when no tool calls in AssistantMessage
        state_1 = AssistantState(messages=[AssistantMessage(content="Hello", tool_calls=[])], root_tool_calls_count=3)
        result = node.run(state_1, {})
        self.assertEqual(result.root_tool_calls_count, 0)

        # Test reset when last message is HumanMessage
        state_2 = AssistantState(messages=[HumanMessage(content="Hello")], root_tool_calls_count=3)
        result = node.run(state_2, {})
        self.assertEqual(result.root_tool_calls_count, 0)
