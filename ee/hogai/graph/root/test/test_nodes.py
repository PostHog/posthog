from unittest.mock import patch

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    HumanMessage as LangchainHumanMessage,
    ToolMessage as LangchainToolMessage,
)
from langchain_core.runnables import RunnableLambda
from parameterized import parameterized

from ee.hogai.graph.root.nodes import RootNode, RootNodeTools
from ee.hogai.utils.test import FakeChatOpenAI
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantMessage, AssistantToolCall, AssistantToolCallMessage, HumanMessage
from posthog.test.base import BaseTest, ClickhouseTestMixin


class TestRootNode(ClickhouseTestMixin, BaseTest):
    def test_node_handles_plain_chat_response(self):
        with patch(
            "ee.hogai.graph.root.nodes.RootNode._get_model",
            return_value=FakeChatOpenAI(
                responses=[LangchainAIMessage(content="Why did the chicken cross the road? To get to the other side!")]
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
            "ee.hogai.graph.root.nodes.RootNode._get_model",
            return_value=FakeChatOpenAI(
                responses=[
                    LangchainAIMessage(
                        content="Hang tight while I check this.",
                        tool_calls=[
                            {
                                "id": "xyz",
                                "name": "create_and_query_insight",
                                "args": {"query_description": "Foobar", "query_kind": insight_type},
                            }
                        ],
                    )
                ],
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
            "ee.hogai.graph.root.nodes.RootNode._get_model",
            return_value=FakeChatOpenAI(
                responses=[
                    LangchainAIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "xyz",
                                "name": "create_and_query_insight",
                                "args": {"query_description": "Foobar", "query_kind": insight_type},
                            }
                        ],
                    )
                ],
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

    @patch("ee.hogai.graph.root.nodes.RootNode._get_model", return_value=FakeChatOpenAI(responses=[]))
    def test_node_reconstructs_conversation(self, mock_model):
        node = RootNode(self.team)
        state_1 = AssistantState(messages=[HumanMessage(content="Hello")])
        self.assertEqual(
            node._construct_and_update_messages_window(state_1, {})[0], [LangchainHumanMessage(content="Hello")]
        )

        # We want full access to message history in root
        state_2 = AssistantState(
            messages=[
                HumanMessage(content="Hello"),
                AssistantMessage(content="Welcome!"),
                HumanMessage(content="Generate trends"),
            ]
        )
        self.assertEqual(
            node._construct_and_update_messages_window(state_2, {})[0],
            [
                LangchainHumanMessage(content="Hello"),
                LangchainAIMessage(content="Welcome!"),
                LangchainHumanMessage(content="Generate trends"),
            ],
        )

    @patch("ee.hogai.graph.root.nodes.RootNode._get_model", return_value=FakeChatOpenAI(responses=[]))
    def test_node_reconstructs_conversation_with_tool_calls(self, mock_model):
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
                AssistantToolCallMessage(content="Answer", tool_call_id="xyz"),
                HumanMessage(content="Answer"),
            ]
        )
        self.assertEqual(
            node._construct_and_update_messages_window(state, {})[0],
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

    @patch("ee.hogai.graph.root.nodes.RootNode._get_model", return_value=FakeChatOpenAI(responses=[]))
    def test_node_filters_tool_calls_without_responses(self, mock_model):
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
        messages, _ = node._construct_and_update_messages_window(state, {})

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
        mock = RunnableLambda(lambda _: LangchainAIMessage(content="I can't help with that anymore."))
        mock.get_num_tokens_from_messages = lambda _: 1

        with patch(
            "ee.hogai.graph.root.nodes.ChatOpenAI",
            return_value=mock,
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
            messages, _ = node._construct_and_update_messages_window(state, {})
            self.assertIn("iterations", messages[-1].content)

    @patch("ee.hogai.graph.root.nodes.RootNode._get_model", return_value=FakeChatOpenAI(responses=[]))
    def test_token_limit_is_respected(self, mock_model):
        # Trims after 64k
        node = RootNode(self.team)
        state = AssistantState(
            messages=[
                HumanMessage(content="Hi" * 64100, id="1"),
                AssistantMessage(content="Bar", id="2"),
                HumanMessage(content="Foo", id="3"),
            ]
        )
        messages, window_id = node._construct_and_update_messages_window(state, {})
        self.assertEqual(len(messages), 1)
        self.assertIn("Foo", messages[0].content)
        self.assertEqual(window_id, "3")

        # Trims for 32k limit after 64k is hit
        state = AssistantState(
            messages=[
                HumanMessage(content="Hi" * 48000, id="1"),
                AssistantMessage(content="Hi" * 24000, id="2"),
                HumanMessage(content="The" * 31000, id="3"),
            ]
        )
        messages, window_id = node._construct_and_update_messages_window(state, {})
        self.assertEqual(len(messages), 1)
        self.assertIn("The", messages[0].content)
        self.assertEqual(window_id, "3")

        # Beyond limit should still return messages.
        state = AssistantState(
            messages=[
                HumanMessage(content="Hi" * 48000, id="1"),
                AssistantMessage(
                    content="Hi" * 24000,
                    id="2",
                    tool_calls=[{"id": "xyz", "name": "create_and_query_insight", "args": {}}],
                ),
                AssistantToolCallMessage(content="The" * 48000, id="3", tool_call_id="xyz"),
            ]
        )
        messages, window_id = node._construct_and_update_messages_window(state, {})
        self.assertEqual(len(messages), 2)
        self.assertIn("Hi", messages[0].content)
        self.assertIn("The", messages[1].content)
        self.assertEqual(window_id, "2")

        state = AssistantState(
            messages=[
                HumanMessage(content="Hi" * 48000, id="1"),
                AssistantMessage(
                    content="Hi" * 24000,
                    id="2",
                ),
                HumanMessage(content="The" * 48000, id="3"),
            ]
        )
        messages, window_id = node._construct_and_update_messages_window(state, {})
        self.assertEqual(len(messages), 1)
        self.assertIn("The", messages[0].content)
        self.assertEqual(window_id, "3")

        # Tool responses are not removed
        state = AssistantState(
            messages=[
                HumanMessage(content="Foo", id="1"),
                AssistantMessage(
                    content="Bar",
                    id="2",
                    tool_calls=[{"id": "xyz", "name": "create_and_query_insight", "args": {}}],
                ),
                AssistantToolCallMessage(content="The" * 65000, id="3", tool_call_id="xyz"),
            ]
        )
        messages, window_id = node._construct_and_update_messages_window(state, {})
        self.assertEqual(len(messages), 2)
        self.assertIn("Bar", messages[0].content)
        self.assertIn("The", messages[1].content)
        self.assertEqual(window_id, "2")

        state = AssistantState(
            messages=[
                HumanMessage(content="Foo", id="1"),
                AssistantMessage(
                    content="Bar",
                    id="2",
                    tool_calls=[{"id": "xyz", "name": "create_and_query_insight", "args": {}}],
                ),
                AssistantToolCallMessage(content="Result", id="3", tool_call_id="xyz"),
                HumanMessage(content="Baz", id="4"),
            ]
        )
        messages, window_id = node._construct_and_update_messages_window(state, {})
        self.assertEqual(len(messages), 4)
        self.assertIsNone(window_id)

    @patch(
        "ee.hogai.graph.root.nodes.RootNode._get_model",
        return_value=FakeChatOpenAI(responses=[LangchainAIMessage(content="Simple response")]),
    )
    def test_run_updates_conversation_window(self, mock_model):
        # Mock the model to return a simple response
        node = RootNode(self.team)

        # Create initial state with a large conversation
        initial_state = AssistantState(
            messages=[
                HumanMessage(content="Foo", id="1"),
                AssistantMessage(content="Bar" * 65000, id="2"),  # Large message to exceed token limit
                HumanMessage(content="Question", id="3"),
            ]
        )

        # First run should set a new window ID
        result_1 = node.run(initial_state, {})
        self.assertIsNotNone(result_1.root_conversation_start_id)
        self.assertEqual(result_1.root_conversation_start_id, "3")  # Should start from last human message

        # Create a new state using the window ID from previous run
        state_2 = AssistantState(
            messages=[*initial_state.messages, *result_1.messages, HumanMessage(content="Follow-up", id="4")],
            root_conversation_start_id=result_1.root_conversation_start_id,
        )

        # Second run should maintain the window
        result_2 = node.run(state_2, {})
        self.assertIsNone(result_2.root_conversation_start_id)  # No new window needed
        self.assertEqual(len(result_2.messages), 1)

        state_3 = AssistantState(
            messages=[*state_2.messages, *result_2.messages],
            root_conversation_start_id=result_2.root_conversation_start_id,
        )

        # Verify the full conversation flow by checking the messages that would be sent to the model
        messages, _ = node._construct_and_update_messages_window(state_3, {})
        self.assertEqual(len(messages), 4)  # Question + Response + Follow-up + New Response
        self.assertEqual(messages[0].content, "Question")  # Starts from the window ID message


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
        self.assertEqual(node.router(state_2), "insights")

        # Test case 3: No tool call message or root tool call - should return "end"
        state_3 = AssistantState(messages=[AssistantMessage(content="Hello")])
        self.assertEqual(node.router(state_3), "end")

        # Test case 4: Has contextual tool call result - should go back to root
        state_4 = AssistantState(
            messages=[
                AssistantMessage(content="Hello"),
                AssistantToolCallMessage(content="Tool result", tool_call_id="xyz"),
            ]
        )
        self.assertEqual(node.router(state_4), "root")

    def test_run_no_assistant_message(self):
        node = RootNodeTools(self.team)
        state = AssistantState(messages=[HumanMessage(content="Hello")])
        self.assertEqual(node.run(state, {}), PartialAssistantState(root_tool_calls_count=0))

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

    def test_run_valid_contextual_tool_call(self):
        node = RootNodeTools(self.team)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Hello",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name="search_session_recordings",
                            args={"change": "Add duration > 5min filter"},
                        )
                    ],
                )
            ]
        )

        with patch(
            "products.replay.backend.max_tools.SearchSessionRecordingsTool._run_impl",
            return_value=("Success", {}),
        ):
            result = node.run(
                state, {"configurable": {"contextual_tools": {"search_session_recordings": {"current_filters": {}}}}}
            )

        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(result.root_tool_call_id, None)  # Tool was fully handled by the node
        self.assertIsNone(result.root_tool_insight_plan)  # No insight plan for contextual tools
        self.assertIsNone(result.root_tool_insight_type)  # No insight type for contextual tools

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
