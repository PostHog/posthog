from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    HumanMessage as LangchainHumanMessage,
    ToolMessage as LangchainToolMessage,
)
from langgraph.errors import NodeInterrupt
from parameterized import parameterized

from ee.hogai.graph.root.nodes import RootNode, RootNodeTools
from ee.hogai.utils.tests import FakeChatOpenAI
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.models.assistant import CoreMemory
from posthog.schema import (
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    DashboardFilter,
    EntityType,
    EventsNode,
    FunnelsQuery,
    HogQLQuery,
    HumanMessage,
    LifecycleQuery,
    MaxActionContext,
    MaxUIContext,
    MaxDashboardContext,
    MaxEventContext,
    MaxInsightContext,
    RetentionEntity,
    RetentionFilter,
    RetentionQuery,
    TrendsQuery,
)
from posthog.test.base import BaseTest, ClickhouseTestMixin


class TestRootNode(ClickhouseTestMixin, BaseTest):
    def test_node_handles_plain_chat_response(self):
        with patch(
            "ee.hogai.graph.root.nodes.RootNode._get_model",
            return_value=FakeChatOpenAI(
                responses=[LangchainAIMessage(content="Why did the chicken cross the road? To get to the other side!")]
            ),
        ):
            node = RootNode(self.team, self.user)
            state_1 = AssistantState(messages=[HumanMessage(content="Tell me a joke")])
            next_state = node.run(state_1, {})
            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 1)
            self.assertIsInstance(next_state.messages[0], AssistantMessage)
            assistant_message = next_state.messages[0]
            assert isinstance(assistant_message, AssistantMessage)
            self.assertEqual(assistant_message.content, "Why did the chicken cross the road? To get to the other side!")

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
            node = RootNode(self.team, self.user)
            state_1 = AssistantState(messages=[HumanMessage(content=f"generate {insight_type}")])
            next_state = node.run(state_1, {})
            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 1)
            assistant_message = next_state.messages[0]
            self.assertIsInstance(assistant_message, AssistantMessage)
            assert isinstance(assistant_message, AssistantMessage)
            self.assertEqual(assistant_message.content, "Hang tight while I check this.")
            self.assertIsNotNone(assistant_message.id)
            self.assertIsNotNone(assistant_message.tool_calls)
            assert assistant_message.tool_calls is not None
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
            node = RootNode(self.team, self.user)
            state_1 = AssistantState(messages=[HumanMessage(content=f"generate {insight_type}")])
            next_state = node.run(state_1, {})
            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 1)
            assistant_message = next_state.messages[0]
            self.assertIsInstance(assistant_message, AssistantMessage)
            assert isinstance(assistant_message, AssistantMessage)
            self.assertEqual(assistant_message.content, "")
            self.assertIsNotNone(assistant_message.id)
            self.assertIsNotNone(assistant_message.tool_calls)
            assert assistant_message.tool_calls is not None
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
        node = RootNode(self.team, self.user)
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
        node = RootNode(self.team, self.user)
        state = AssistantState(
            messages=[
                HumanMessage(content="Hello"),
                AssistantMessage(
                    content="Welcome!",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name="create_and_query_insight",
                            args={},
                        )
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
        node = RootNode(self.team, self.user)
        state = AssistantState(
            messages=[
                HumanMessage(content="Hello"),
                AssistantMessage(
                    content="Welcome!",
                    tool_calls=[
                        # This tool call has a response
                        AssistantToolCall(
                            id="xyz1",
                            name="create_and_query_insight",
                            args={},
                        ),
                        # This tool call has no response and should be filtered out
                        AssistantToolCall(
                            id="xyz2",
                            name="create_and_query_insight",
                            args={},
                        ),
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
        assert isinstance(assistant_message, LangchainAIMessage)
        self.assertEqual(assistant_message.content, "Welcome!")
        self.assertEqual(len(assistant_message.tool_calls), 1)
        self.assertEqual(assistant_message.tool_calls[0]["id"], "xyz1")

        # Verify the tool response is included
        tool_message = messages[2]
        self.assertIsInstance(tool_message, LangchainToolMessage)
        assert isinstance(tool_message, LangchainToolMessage)
        self.assertEqual(tool_message.content, "Answer for xyz1")
        self.assertEqual(tool_message.tool_call_id, "xyz1")

    def test_hard_limit_removes_tools(self):
        mock_with_tokens = MagicMock()
        mock_with_tokens.side_effect = lambda _: LangchainAIMessage(content="I can't help with that anymore.")
        mock_with_tokens.get_num_tokens_from_messages = MagicMock(return_value=1)

        with patch(
            "ee.hogai.graph.root.nodes.ChatOpenAI",
            return_value=mock_with_tokens,
        ):
            node = RootNode(self.team, self.user)

            # Create a state that has hit the hard limit (4 tool calls)
            state = AssistantState(messages=[HumanMessage(content="Hello")], root_tool_calls_count=4)

            # Run the node
            next_state = node.run(state, {})

            # Verify the response doesn't contain any tool calls
            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 1)
            message = next_state.messages[0]
            self.assertIsInstance(message, AssistantMessage)
            assert isinstance(message, AssistantMessage)
            self.assertEqual(message.content, "I can't help with that anymore.")
            self.assertEqual(message.tool_calls, [])

            # Verify the hard limit message was added to the conversation
            messages, _ = node._construct_and_update_messages_window(state, {})
            self.assertIn("iterations", messages[-1].content)

    @patch("ee.hogai.graph.root.nodes.RootNode._get_model", return_value=FakeChatOpenAI(responses=[]))
    def test_token_limit_is_respected(self, mock_model):
        # Trims after 64k
        node = RootNode(self.team, self.user)
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
                    tool_calls=[AssistantToolCall(id="xyz", name="create_and_query_insight", args={})],
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
                    tool_calls=[AssistantToolCall(id="xyz", name="create_and_query_insight", args={})],
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
                    tool_calls=[AssistantToolCall(id="xyz", name="create_and_query_insight", args={})],
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
        node = RootNode(self.team, self.user)

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

    def test_node_gets_contextual_tool(self):
        with patch("ee.hogai.graph.root.nodes.ChatOpenAI") as mock_chat_openai:
            mock_model = MagicMock()
            mock_model.get_num_tokens_from_messages.return_value = 100
            mock_model.bind_tools.return_value = mock_model
            mock_chat_openai.return_value = mock_model

            node = RootNode(self.team, self.user)

            node._get_model(
                AssistantState(messages=[HumanMessage(content="show me long recordings")]),
                {
                    "configurable": {
                        "contextual_tools": {"search_session_recordings": {"current_filters": {"duration": ">"}}}
                    }
                },
            )

            # Verify bind_tools was called (contextual tools were processed)
            mock_model.bind_tools.assert_called_once()
            tools = mock_model.bind_tools.call_args[0][0]
            # Verify the search_session_recordings tool was included
            tool_names = [getattr(tool, "name", None) or tool.__name__ for tool in tools]
            self.assertIn("search_session_recordings", tool_names)

    def test_node_does_not_get_contextual_tool_if_not_configured(self):
        with (
            patch(
                "ee.hogai.graph.root.nodes.RootNode._get_model",
                return_value=FakeChatOpenAI(responses=[LangchainAIMessage(content="Simple response")]),
            ),
            patch("ee.hogai.utils.tests.FakeChatOpenAI.bind_tools", return_value=MagicMock()) as mock_bind_tools,
            patch(
                "products.replay.backend.max_tools.SearchSessionRecordingsTool._run_impl",
                return_value=("Success", {}),
            ),
        ):
            node = RootNode(self.team, self.user)
            state = AssistantState(messages=[HumanMessage(content="show me long recordings")])

            next_state = node.run(state, {})

            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 1)
            assistant_message = next_state.messages[0]
            self.assertIsInstance(assistant_message, AssistantMessage)
            assert isinstance(assistant_message, AssistantMessage)
            self.assertEqual(assistant_message.content, "Simple response")
            self.assertEqual(assistant_message.tool_calls, [])
            mock_bind_tools.assert_not_called()

    def test_node_injects_contextual_tool_prompts(self):
        with patch("ee.hogai.graph.root.nodes.RootNode._get_model") as mock_get_model:
            # Use FakeChatOpenAI like other tests
            fake_model = FakeChatOpenAI(responses=[LangchainAIMessage(content="I'll help with recordings")])
            mock_get_model.return_value = fake_model

            node = RootNode(self.team, self.user)
            state = AssistantState(messages=[HumanMessage(content="show me long recordings")])

            # Test with contextual tools
            result = node.run(
                state,
                {
                    "configurable": {
                        "contextual_tools": {"search_session_recordings": {"current_filters": {"duration": ">"}}}
                    }
                },
            )

            # Verify the node ran successfully and returned a message
            self.assertIsInstance(result, PartialAssistantState)
            self.assertEqual(len(result.messages), 1)
            # The message should be an AssistantMessage, not VisualizationMessage
            self.assertIsInstance(result.messages[0], AssistantMessage)
            assert isinstance(result.messages[0], AssistantMessage)
            self.assertEqual(result.messages[0].content, "I'll help with recordings")

            # Verify _get_model was called with contextual tools config
            mock_get_model.assert_called()
            config_arg = mock_get_model.call_args[0][1]
            self.assertIn("contextual_tools", config_arg["configurable"])
            self.assertIn("search_session_recordings", config_arg["configurable"]["contextual_tools"])

    def test_node_includes_project_org_user_context_in_prompt_template(self):
        with (
            # This test mocks deeper than ideal, and really it should be spying on the actual LLM call, rather than
            # prompt template construction. However, LangChain's chaining mechanics make it even more painful to
            # mock the "right" thing, so going for a kludge here.
            patch("ee.hogai.graph.root.nodes.ChatPromptTemplate.from_messages") as mock_chat_prompt_template,
            patch("ee.hogai.graph.root.nodes.ChatOpenAI") as mock_chat_openai,
            patch("ee.hogai.graph.root.nodes.RootNode._find_new_window_id", return_value=None),
        ):
            mock_model = MagicMock()
            mock_model.bind_tools.return_value = mock_model
            mock_chat_openai.return_value = mock_model

            node = RootNode(self.team, self.user)

            node.run(AssistantState(messages=[HumanMessage(content="Foo?")]), {})

            mock_chat_prompt_template.assert_called_once()
            system_content = "\n\n".join(
                content for role, content in mock_chat_prompt_template.call_args[0][0] if role == "system"
            )
            self.assertIn("You are currently in project ", system_content)
            self.assertIn("The user's name appears to be ", system_content)

    def test_model_has_correct_max_retries(self):
        with patch("ee.hogai.graph.root.nodes.ChatOpenAI") as mock_chat_openai:
            mock_model = MagicMock()
            mock_model.get_num_tokens_from_messages.return_value = 100
            mock_model.bind_tools.return_value = mock_model
            mock_chat_openai.return_value = mock_model

            node = RootNode(self.team, self.user)
            state = AssistantState(messages=[HumanMessage(content="test")])

            node._get_model(state, {})

            # Verify ChatOpenAI was called with max_retries=3
            mock_chat_openai.assert_called_once()
            call_args = mock_chat_openai.call_args
            self.assertEqual(call_args.kwargs["max_retries"], 3)


class TestRootNodeTools(BaseTest):
    def test_node_tools_router(self):
        node = RootNodeTools(self.team, self.user)

        # Test case 1: Last message is AssistantToolCallMessage - should return "root"
        state_1 = AssistantState(
            messages=[
                HumanMessage(content="Hello"),
                AssistantToolCallMessage(content="Tool result", tool_call_id="xyz"),
            ]
        )
        self.assertEqual(node.router(state_1), "root")

        # Test case 2: Has root tool call with query_kind - should return that query_kind
        # If the user has not completed the onboarding, it should return memory_onboarding instead
        state_2 = AssistantState(
            messages=[AssistantMessage(content="Hello")],
            root_tool_call_id="xyz",
            root_tool_insight_plan="Foobar",
            root_tool_insight_type="trends",
        )
        self.assertEqual(node.router(state_2), "memory_onboarding")
        core_memory = CoreMemory.objects.create(team=self.team)
        core_memory.change_status_to_skipped()
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

    async def test_run_no_assistant_message(self):
        node = RootNodeTools(self.team, self.user)
        state = AssistantState(messages=[HumanMessage(content="Hello")])
        result = await node.arun(state, {})
        self.assertEqual(result, PartialAssistantState(root_tool_calls_count=0))

    async def test_run_valid_tool_call(self):
        node = RootNodeTools(self.team, self.user)
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
        result = await node.arun(state, {})
        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(result.root_tool_call_id, "xyz")
        self.assertEqual(result.root_tool_insight_plan, "test query")
        self.assertEqual(result.root_tool_insight_type, "trends")

    async def test_run_valid_contextual_tool_call(self):
        node = RootNodeTools(self.team, self.user)
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
            result = await node.arun(
                state,
                {
                    "configurable": {
                        "team": self.team,
                        "user": self.user,
                        "contextual_tools": {"search_session_recordings": {"current_filters": {}}},
                    }
                },
            )

        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(result.root_tool_call_id, None)  # Tool was fully handled by the node
        self.assertIsNone(result.root_tool_insight_plan)  # No insight plan for contextual tools
        self.assertIsNone(result.root_tool_insight_type)  # No insight type for contextual tools
        self.assertTrue(result.messages[-1].visible)  # The tool call must have the visible attribute set

    async def test_run_multiple_tool_calls_raises(self):
        node = RootNodeTools(self.team, self.user)
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
            await node.arun(state, {})
        self.assertEqual(str(cm.exception), "Expected exactly one tool call.")

    async def test_run_increments_tool_count(self):
        node = RootNodeTools(self.team, self.user)
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
        result = await node.arun(state, {})
        self.assertEqual(result.root_tool_calls_count, 3)  # Should increment by 1

    async def test_run_resets_tool_count(self):
        node = RootNodeTools(self.team, self.user)

        # Test reset when no tool calls in AssistantMessage
        state_1 = AssistantState(messages=[AssistantMessage(content="Hello", tool_calls=[])], root_tool_calls_count=3)
        result = await node.arun(state_1, {})
        self.assertEqual(result.root_tool_calls_count, 0)

        # Test reset when last message is HumanMessage
        state_2 = AssistantState(messages=[HumanMessage(content="Hello")], root_tool_calls_count=3)
        result = await node.arun(state_2, {})
        self.assertEqual(result.root_tool_calls_count, 0)

    async def test_navigate_tool_call_raises_node_interrupt(self):
        """Test that navigate tool calls raise NodeInterrupt to pause graph execution"""
        node = RootNodeTools(self.team, self.user)

        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="I'll help you navigate to insights",
                    id="test-id",
                    tool_calls=[AssistantToolCall(id="nav-123", name="navigate", args={"page_key": "insights"})],
                )
            ]
        )

        with patch("ee.hogai.tool.get_contextual_tool_class") as mock_tools:
            # Mock the navigate tool
            mock_navigate_tool = AsyncMock()
            mock_navigate_tool.ainvoke.return_value = LangchainToolMessage(
                content="XXX", tool_call_id="nav-123", artifact={"page_key": "insights"}
            )
            mock_tools.return_value = lambda _: mock_navigate_tool

            # The navigate tool call should raise NodeInterrupt
            with self.assertRaises(NodeInterrupt) as cm:
                await node.arun(state, {"configurable": {"contextual_tools": {"navigate": {}}}})

            # Verify the NodeInterrupt contains the expected message
            # NodeInterrupt wraps the message in an Interrupt object
            interrupt_data = cm.exception.args[0]
            if isinstance(interrupt_data, list):
                interrupt_data = interrupt_data[0].value
            self.assertIsInstance(interrupt_data, AssistantToolCallMessage)
            self.assertEqual(interrupt_data.content, "XXX")
            self.assertEqual(interrupt_data.tool_call_id, "nav-123")
            self.assertTrue(interrupt_data.visible)
            self.assertEqual(interrupt_data.ui_payload, {"navigate": {"page_key": "insights"}})

    async def test_non_navigate_contextual_tool_call_does_not_raise_interrupt(self):
        """Test that non-navigate contextual tool calls don't raise NodeInterrupt"""
        node = RootNodeTools(self.team, self.user)

        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Let me search for recordings",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(id="search-123", name="search_session_recordings", args={"change": "test"})
                    ],
                )
            ]
        )

        with patch("ee.hogai.tool.get_contextual_tool_class") as mock_tools:
            # Mock the search_session_recordings tool
            mock_search_session_recordings = AsyncMock()
            mock_search_session_recordings.ainvoke.return_value = LangchainToolMessage(
                content="YYYY", tool_call_id="nav-123", artifact={"filters": {}}
            )
            mock_tools.return_value = lambda _: mock_search_session_recordings

            # This should not raise NodeInterrupt
            result = await node.arun(
                state,
                {
                    "configurable": {
                        "team": self.team,
                        "user": self.user,
                        "contextual_tools": {"search_session_recordings": {"current_filters": {}}},
                    }
                },
            )

            # Should return a normal result
            self.assertIsInstance(result, PartialAssistantState)
            self.assertIsNone(result.root_tool_call_id)
            self.assertEqual(len(result.messages), 1)
            self.assertIsInstance(result.messages[0], AssistantToolCallMessage)


class TestRootNodeUIContextMixin(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.mixin = RootNode(self.team, self.user)  # Using RootNode since it inherits from RootNodeUIContextMixin

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor")
    def test_run_and_format_insight_trends_query(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.run_and_format_query.return_value = ("Trend results: 100 users", None)

        insight = MaxInsightContext(
            id="123",
            name="User Trends",
            description="Daily active users",
            query=TrendsQuery(series=[EventsNode(event="pageview")]),
        )

        result = self.mixin._run_and_format_insight(insight, mock_query_runner, heading="#")
        expected = """# Insight: User Trends

Description: Daily active users

Query schema:
```json
{"filterTestAccounts":false,"interval":"day","kind":"TrendsQuery","properties":[],"series":[{"event":"pageview","kind":"EventsNode"}]}
```

Results:
```
Trend results: 100 users
```"""
        self.assertEqual(result, expected)
        mock_query_runner.run_and_format_query.assert_called_once()

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor")
    def test_run_and_format_insight_funnel_query(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.run_and_format_query.return_value = ("Funnel results: 50% conversion", None)

        insight = MaxInsightContext(
            id="456",
            name="Conversion Funnel",
            description=None,
            query=FunnelsQuery(series=[EventsNode(event="sign_up"), EventsNode(event="purchase")]),
        )

        result = self.mixin._run_and_format_insight(insight, mock_query_runner, heading="#")

        expected = """# Insight: Conversion Funnel

Query schema:
```json
{"filterTestAccounts":false,"kind":"FunnelsQuery","properties":[],"series":[{"event":"sign_up","kind":"EventsNode"},{"event":"purchase","kind":"EventsNode"}]}
```

Results:
```
Funnel results: 50% conversion
```"""
        self.assertEqual(result, expected)

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor")
    def test_run_and_format_insight_retention_query(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.run_and_format_query.return_value = ("Retention: 30% Day 7", None)

        insight = MaxInsightContext(
            id="789",
            name=None,
            description=None,
            query=RetentionQuery(
                retentionFilter=RetentionFilter(
                    targetEntity=RetentionEntity(id="$pageview", type=EntityType.EVENTS),
                    returningEntity=RetentionEntity(id="$pageview", type=EntityType.EVENTS),
                )
            ),
        )

        result = self.mixin._run_and_format_insight(insight, mock_query_runner, heading="#")
        expected = """# Insight: ID 789

Query schema:
```json
{"filterTestAccounts":false,"kind":"RetentionQuery","properties":[],"retentionFilter":{"period":"Day","returningEntity":{"id":"$pageview","type":"events"},"targetEntity":{"id":"$pageview","type":"events"},"totalIntervals":8}}
```

Results:
```
Retention: 30% Day 7
```"""
        self.assertEqual(result, expected)

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor")
    def test_run_and_format_insight_hogql_query(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.run_and_format_query.return_value = ("Query results: 42 events", None)

        insight = MaxInsightContext(
            id="101",
            name="Custom Query",
            description="HogQL analysis",
            query=HogQLQuery(query="SELECT count() FROM events"),
        )

        result = self.mixin._run_and_format_insight(insight, mock_query_runner, heading="#")
        expected = """# Insight: Custom Query

Description: HogQL analysis

Query schema:
```json
{"kind":"HogQLQuery","query":"SELECT count() FROM events"}
```

Results:
```
Query results: 42 events
```"""
        self.assertEqual(result, expected)

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor")
    def test_run_and_format_insight_unsupported_query_kind(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value

        insight = MaxInsightContext(id="123", name="Unsupported", description=None, query=LifecycleQuery(series=[]))

        result = self.mixin._run_and_format_insight(insight, mock_query_runner)

        self.assertEqual(result, None)
        mock_query_runner.run_and_format_query.assert_not_called()

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor")
    def test_run_and_format_insight_exception_handling(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.run_and_format_query.side_effect = Exception("Query failed")

        insight = MaxInsightContext(
            id="123",
            name="Failed Query",
            description=None,
            query=TrendsQuery(series=[EventsNode(event="pageview")]),
        )

        result = self.mixin._run_and_format_insight(insight, mock_query_runner)

        self.assertEqual(result, None)

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor")
    def test_format_ui_context_with_dashboard(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.run_and_format_query.return_value = ("Dashboard insight results", None)

        # Create mock insight
        insight = MaxInsightContext(
            id="123",
            name="Dashboard Insight",
            description="Test insight",
            query=TrendsQuery(series=[EventsNode(event="pageview")]),
        )

        # Create mock dashboard
        dashboard = MaxDashboardContext(
            id=456,
            name="Test Dashboard",
            description="Test dashboard description",
            insights=[insight],
            filters=DashboardFilter(),
        )

        # Create mock UI context
        ui_context = MaxUIContext(dashboards=[dashboard], insights=None)

        result = self.mixin._format_ui_context(ui_context)

        self.assertIn("Dashboard: Test Dashboard", result)
        self.assertIn("Description: Test dashboard description", result)
        self.assertIn("### Dashboard insights", result)
        self.assertIn("Insight: Dashboard Insight", result)
        self.assertNotIn("# Insights", result)

    def test_format_ui_context_with_events(self):
        # Create mock events
        event1 = MaxEventContext(id="1", name="page_view")
        event2 = MaxEventContext(id="2", name="button_click")

        # Create mock UI context
        ui_context = MaxUIContext(dashboards=None, insights=None, events=[event1, event2], actions=None)

        result = self.mixin._format_ui_context(ui_context)

        self.assertIn('"page_view", "button_click"', result)
        self.assertIn("<events_context>", result)

    def test_format_ui_context_with_events_with_descriptions(self):
        # Create mock events with descriptions
        event1 = MaxEventContext(id="1", name="page_view", description="User viewed a page")
        event2 = MaxEventContext(id="2", name="button_click", description="User clicked a button")

        # Create mock UI context
        ui_context = MaxUIContext(dashboards=None, insights=None, events=[event1, event2], actions=None)

        result = self.mixin._format_ui_context(ui_context)

        self.assertIn('"page_view: User viewed a page", "button_click: User clicked a button"', result)
        self.assertIn("<events_context>", result)

    def test_format_ui_context_with_actions(self):
        # Create mock actions
        action1 = MaxActionContext(id=1.0, name="Sign Up")
        action2 = MaxActionContext(id=2.0, name="Purchase")

        # Create mock UI context
        ui_context = MaxUIContext(dashboards=None, insights=None, events=None, actions=[action1, action2])

        result = self.mixin._format_ui_context(ui_context)

        self.assertIn('"Sign Up", "Purchase"', result)
        self.assertIn("<actions_context>", result)

    def test_format_ui_context_with_actions_with_descriptions(self):
        # Create mock actions with descriptions
        action1 = MaxActionContext(id=1.0, name="Sign Up", description="User creates account")
        action2 = MaxActionContext(id=2.0, name="Purchase", description="User makes a purchase")

        # Create mock UI context
        ui_context = MaxUIContext(dashboards=None, insights=None, events=None, actions=[action1, action2])

        result = self.mixin._format_ui_context(ui_context)

        self.assertIn('"Sign Up: User creates account", "Purchase: User makes a purchase"', result)
        self.assertIn("<actions_context>", result)

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor")
    def test_format_ui_context_with_standalone_insights(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.run_and_format_query.return_value = ("Standalone insight results", None)

        # Create mock insight
        insight = MaxInsightContext(
            id="123",
            name="Standalone Insight",
            description="Test standalone insight",
            query=FunnelsQuery(series=[EventsNode(event="sign_up")]),
        )

        # Create mock UI context
        ui_context = MaxUIContext(insights=[insight])

        result = self.mixin._format_ui_context(ui_context)

        self.assertIn("Insights", result)
        self.assertIn("Insight: Standalone Insight", result)
        self.assertNotIn("# Dashboards", result)

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor")
    def test_run_insights_from_ui_context_empty(self, mock_query_runner_class):
        result = self.mixin._format_ui_context(None)
        self.assertEqual(result, "")

        # Test with ui_context but no insights
        ui_context = MaxUIContext(insights=None)
        result = self.mixin._format_ui_context(ui_context)
        self.assertEqual(result, "")

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor")
    def test_run_insights_from_ui_context_with_insights(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.run_and_format_query.return_value = ("Insight execution results", None)

        # Create mock insight
        insight = MaxInsightContext(
            id="123",
            name="Test Insight",
            description="Test description",
            query=TrendsQuery(series=[EventsNode(event="pageview")]),
        )

        # Create mock UI context
        ui_context = MaxUIContext(insights=[insight])

        result = self.mixin._format_ui_context(ui_context)

        self.assertIn("# Insights", result)
        self.assertIn("Test Insight", result)
        self.assertIn("Test description", result)
        self.assertIn("Insight execution results", result)

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor")
    def test_run_insights_from_ui_context_with_failed_insights(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.run_and_format_query.side_effect = Exception("Query failed")

        # Create mock insight that will fail
        insight = MaxInsightContext(
            id="123",
            name="Failed Insight",
            description=None,
            query=TrendsQuery(series=[]),
        )

        # Create mock UI context
        ui_context = MaxUIContext(insights=[insight])

        result = self.mixin._format_ui_context(ui_context)

        # Should return empty string since the insight failed to run
        self.assertEqual(result, "")
