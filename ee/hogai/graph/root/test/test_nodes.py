import datetime
from typing import cast

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import (
    AIMessage,
    AIMessage as LangchainAIMessage,
    HumanMessage as LangchainHumanMessage,
    SystemMessage,
    ToolMessage as LangchainToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig
from langgraph.errors import NodeInterrupt
from parameterized import parameterized

from posthog.schema import (
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    ContextMessage,
    DashboardFilter,
    EntityType,
    EventsNode,
    FunnelsQuery,
    HogQLQuery,
    HumanMessage,
    LifecycleQuery,
    MaxActionContext,
    MaxBillingContext,
    MaxBillingContextSettings,
    MaxBillingContextSubscriptionLevel,
    MaxBillingContextTrial,
    MaxDashboardContext,
    MaxEventContext,
    MaxInsightContext,
    MaxUIContext,
    RetentionEntity,
    RetentionFilter,
    RetentionQuery,
    TrendsQuery,
)

from posthog.models.organization import OrganizationMembership

from ee.hogai.graph.root.nodes import RootNode, RootNodeTools
from ee.hogai.graph.root.prompts import (
    ROOT_BILLING_CONTEXT_ERROR_PROMPT,
    ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT,
    ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT,
)
from ee.hogai.utils.tests import FakeChatAnthropic, FakeChatOpenAI
from ee.hogai.utils.types import AssistantState, PartialAssistantState


class TestRootNode(ClickhouseTestMixin, BaseTest):
    def _create_billing_context(self):
        """Helper to create test billing context"""
        return MaxBillingContext(
            subscription_level=MaxBillingContextSubscriptionLevel.PAID,
            has_active_subscription=True,
            products=[],
            settings=MaxBillingContextSettings(autocapture_on=True, active_destinations=0),
            trial=MaxBillingContextTrial(is_active=True, expires_at=str(datetime.date(2023, 2, 1)), target="scale"),
        )

    async def test_node_handles_plain_chat_response(self):
        with patch(
            "ee.hogai.graph.root.nodes.RootNode._get_model",
            return_value=FakeChatOpenAI(
                responses=[LangchainAIMessage(content="Why did the chicken cross the road? To get to the other side!")]
            ),
        ):
            node = RootNode(self.team, self.user)
            state_1 = AssistantState(messages=[HumanMessage(content="Tell me a joke")])
            next_state = await node.arun(state_1, {})
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
    async def test_node_handles_insight_tool_call(self, insight_type):
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
            next_state = await node.arun(state_1, {})
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
    async def test_node_handles_insight_tool_call_without_message(self, insight_type):
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
            next_state = await node.arun(state_1, {})
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
    async def test_node_reconstructs_conversation(self, mock_model):
        node = RootNode(self.team, self.user)
        state_1 = AssistantState(messages=[HumanMessage(content="Hello")])
        result = await node._construct_and_update_messages_window(state_1, {})
        self.assertEqual(
            result[0],
            [
                LangchainHumanMessage(
                    content=[{"text": "Hello", "type": "text", "cache_control": {"type": "ephemeral"}}]
                )
            ],
        )

        # We want full access to message history in root
        state_2 = AssistantState(
            messages=[
                HumanMessage(content="Hello"),
                AssistantMessage(content="Welcome!"),
                HumanMessage(content="Generate trends"),
            ]
        )
        result2 = await node._construct_and_update_messages_window(state_2, {})
        self.assertEqual(
            result2[0],
            [
                LangchainHumanMessage(content=[{"text": "Hello", "type": "text"}]),
                LangchainAIMessage(content=[{"text": "Welcome!", "type": "text"}]),
                LangchainHumanMessage(
                    content=[{"text": "Generate trends", "type": "text", "cache_control": {"type": "ephemeral"}}]
                ),
            ],
        )

    @patch("ee.hogai.graph.root.nodes.RootNode._get_model", return_value=FakeChatAnthropic(responses=[]))
    async def test_node_reconstructs_conversation_with_tool_calls(self, mock_model):
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
        result = await node._construct_and_update_messages_window(state, {})
        self.assertEqual(
            result[0],
            [
                LangchainHumanMessage(content=[{"text": "Hello", "type": "text"}]),
                LangchainAIMessage(
                    content=[{"text": "Welcome!", "type": "text"}],
                    tool_calls=[
                        {
                            "id": "xyz",
                            "name": "create_and_query_insight",
                            "args": {},
                        }
                    ],
                ),
                LangchainHumanMessage(content=[{"type": "tool_result", "tool_use_id": "xyz", "content": "Answer"}]),
                LangchainAIMessage(content=[{"text": "Follow-up", "type": "text"}]),
                LangchainHumanMessage(
                    content=[{"text": "Answer", "type": "text", "cache_control": {"type": "ephemeral"}}]
                ),
            ],
        )

    @patch("ee.hogai.graph.root.nodes.RootNode._get_model", return_value=FakeChatOpenAI(responses=[]))
    async def test_node_filters_tool_calls_without_responses(self, mock_model):
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
        messages, _ = await node._construct_and_update_messages_window(state, {})

        # Verify we get exactly 3 messages
        self.assertEqual(len(messages), 3)

        # Verify the messages are in correct order and format
        self.assertEqual(messages[0], LangchainHumanMessage(content=[{"text": "Hello", "type": "text"}]))

        # Verify the assistant message only includes the tool call that has a response
        assistant_message = messages[1]
        self.assertIsInstance(assistant_message, LangchainAIMessage)
        assert isinstance(assistant_message, LangchainAIMessage)
        self.assertEqual(assistant_message.content, [{"text": "Welcome!", "type": "text"}])
        self.assertEqual(len(assistant_message.tool_calls), 1)
        self.assertEqual(assistant_message.tool_calls[0]["id"], "xyz1")

        # Verify the tool response is included
        tool_message = messages[2]
        self.assertIsInstance(tool_message, LangchainHumanMessage)
        assert isinstance(tool_message, LangchainHumanMessage)
        self.assertEqual(
            tool_message.content,
            [
                {
                    "content": "Answer for xyz1",
                    "type": "tool_result",
                    "tool_use_id": "xyz1",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        )

    async def test_hard_limit_removes_tools(self):
        mock_with_tokens = MagicMock()
        ainvoke_mock = AsyncMock()
        ainvoke_mock.return_value = LangchainAIMessage(
            content=[{"text": "I can't help with that anymore.", "type": "text"}], id="1"
        )
        mock_with_tokens.ainvoke = ainvoke_mock
        mock_with_tokens.get_num_tokens_from_messages = MagicMock(return_value=1)

        with patch(
            "ee.hogai.graph.root.nodes.MaxChatAnthropic",
            return_value=mock_with_tokens,
        ):
            node = RootNode(self.team, self.user)

            # Create a state that has hit the hard limit (4 tool calls)
            state = AssistantState(messages=[HumanMessage(content="Hello")], root_tool_calls_count=4)

            # Run the node
            next_state = await node.arun(state, {})

            # Verify the response doesn't contain any tool calls
            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 1)
            message = next_state.messages[0]
            self.assertIsInstance(message, AssistantMessage)
            assert isinstance(message, AssistantMessage)
            self.assertEqual(message.content, "I can't help with that anymore.")
            self.assertEqual(message.tool_calls, [])

            # Verify the hard limit message was added to the conversation
            messages, _ = await node._construct_and_update_messages_window(state, {})
            self.assertIn("iterations", messages[-1].content)

    def test_node_gets_contextual_tool(self):
        with patch("ee.hogai.graph.root.nodes.MaxChatAnthropic") as mock_chat_openai:
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

    async def test_node_does_not_get_contextual_tool_if_not_configured(self):
        with (
            patch(
                "ee.hogai.graph.root.nodes.RootNode._get_model",
                return_value=FakeChatOpenAI(responses=[LangchainAIMessage(content="Simple response")]),
            ),
            patch("ee.hogai.utils.tests.FakeChatOpenAI.bind_tools", return_value=MagicMock()) as mock_bind_tools,
            patch(
                "products.replay.backend.max_tools.SearchSessionRecordingsTool._arun_impl",
                return_value=("Success", {}),
            ),
        ):
            node = RootNode(self.team, self.user)
            state = AssistantState(messages=[HumanMessage(content="show me long recordings")])

            next_state = await node.arun(state, {})

            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 1)
            assistant_message = next_state.messages[0]
            self.assertIsInstance(assistant_message, AssistantMessage)
            assert isinstance(assistant_message, AssistantMessage)
            self.assertEqual(assistant_message.content, "Simple response")
            self.assertEqual(assistant_message.tool_calls, [])
            mock_bind_tools.assert_not_called()

    async def test_node_injects_contextual_tool_prompts(self):
        with patch("ee.hogai.graph.root.nodes.RootNode._get_model") as mock_get_model:
            # Use FakeChatAnthropic like other tests
            fake_model = FakeChatAnthropic(
                responses=[LangchainAIMessage(content=[{"text": "I'll help with recordings", "type": "text"}])]
            )
            mock_get_model.return_value = fake_model

            node = RootNode(self.team, self.user)
            state = AssistantState(messages=[HumanMessage(content="show me long recordings")])

            # Test with contextual tools
            result = await node.arun(
                state,
                {
                    "configurable": {
                        "contextual_tools": {"search_session_recordings": {"current_filters": {"duration": ">"}}}
                    }
                },
            )

            # Verify the node ran successfully and returned a message
            self.assertIsInstance(result, PartialAssistantState)
            self.assertEqual(len(result.messages), 3)
            # Context message
            self.assertIsInstance(result.messages[0], ContextMessage)
            assert isinstance(result.messages[0], ContextMessage)
            self.assertIn("search_session_recordings", result.messages[0].content)
            # Original human message
            self.assertIsInstance(result.messages[1], HumanMessage)
            # The message should be an AssistantMessage, not VisualizationMessage
            self.assertIsInstance(result.messages[2], AssistantMessage)
            assert isinstance(result.messages[2], AssistantMessage)
            self.assertEqual(result.messages[2].content, "I'll help with recordings")

            # Verify _get_model was called with contextual tools config
            mock_get_model.assert_called()
            config_arg = mock_get_model.call_args[0][1]
            self.assertIn("contextual_tools", config_arg["configurable"])
            self.assertIn("search_session_recordings", config_arg["configurable"]["contextual_tools"])

    async def test_node_includes_project_org_user_context_in_prompt_template(self):
        with (
            patch("os.environ", {"ANTHROPIC_API_KEY": "foo"}),
            patch("langchain_anthropic.chat_models.ChatAnthropic._agenerate") as mock_generate,
            patch("ee.hogai.graph.root.nodes.RootNode._find_new_window_id", return_value=None),
        ):
            mock_generate.return_value = ChatResult(
                generations=[ChatGeneration(message=AIMessage(content="Test response"))],
                llm_output={},
            )

            node = RootNode(self.team, self.user)

            await node.arun(AssistantState(messages=[HumanMessage(content="Foo?")]), {})

            # Verify _generate was called
            mock_generate.assert_called_once()

            # Get the messages passed to _generate
            call_args = mock_generate.call_args
            messages = call_args[0][0]  # First argument is messages

            # Check that the system messages contain the project/org/user context
            system_messages = [msg for msg in messages if isinstance(msg, SystemMessage)]
            content_parts = []
            for msg in system_messages:
                if isinstance(msg.content, str):
                    content_parts.append(msg.content)
                else:
                    content_parts.append(str(msg.content))
            system_content = "\n\n".join(content_parts)

            self.assertIn("You are currently in project ", system_content)
            self.assertIn("The user's name appears to be ", system_content)

    @parameterized.expand(
        [
            # (membership_level, has_billing_context, should_add_billing_tool, expected_prompt)
            [OrganizationMembership.Level.ADMIN, True, True, ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT],
            [OrganizationMembership.Level.ADMIN, False, False, ROOT_BILLING_CONTEXT_ERROR_PROMPT],
            [OrganizationMembership.Level.OWNER, True, True, ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT],
            [OrganizationMembership.Level.OWNER, False, False, ROOT_BILLING_CONTEXT_ERROR_PROMPT],
            [OrganizationMembership.Level.MEMBER, True, False, ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT],
            [OrganizationMembership.Level.MEMBER, False, False, ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT],
        ]
    )
    async def test_has_billing_access(
        self, membership_level, has_billing_context, should_add_billing_tool, expected_prompt
    ):
        # Set membership level
        membership = await self.user.organization_memberships.aget(organization=self.team.organization)
        membership.level = membership_level
        await membership.asave()

        node = RootNode(self.team, self.user)

        # Configure billing context if needed
        if has_billing_context:
            billing_context = self._create_billing_context()
            config = RunnableConfig(configurable={"billing_context": billing_context.model_dump()})
        else:
            config = RunnableConfig(configurable={})

        self.assertEqual(await node._get_billing_info(config), (should_add_billing_tool, expected_prompt))

    async def test_deduplicate_context_messages(self):
        """Test that context messages are deduplicated based on existing human message content"""
        node = RootNode(self.team, self.user)

        # Create state with existing human messages
        state = AssistantState(
            messages=[
                HumanMessage(content="Existing message 1"),
                AssistantMessage(content="Response"),
                HumanMessage(content="Existing message 2"),
            ]
        )

        # Test deduplication - should filter out matching content
        context_prompts = [
            "New context message",
            "Existing message 1",  # This should be filtered out
            "Another new message",
            "Existing message 2",  # This should be filtered out
        ]

        result = node._deduplicate_context_messages(state, context_prompts)

        expected = ["New context message", "Another new message"]
        self.assertEqual(result, expected)

    async def test_get_context_prompts_with_ui_and_contextual_tools(self):
        """Test that context prompts are returned for both UI context and contextual tools"""
        with (
            patch.object(RootNode, "_get_contextual_tools_prompt") as mock_contextual_tools,
            patch.object(RootNode, "_format_ui_context") as mock_format_ui,
            patch.object(RootNode, "_get_ui_context") as mock_get_ui,
            patch.object(RootNode, "_deduplicate_context_messages") as mock_dedupe,
        ):
            # Setup mocks
            mock_contextual_tools.return_value = "Contextual tools prompt"
            mock_format_ui.return_value = "UI context prompt"
            mock_get_ui.return_value = MaxUIContext()
            mock_dedupe.return_value = ["Contextual tools prompt", "UI context prompt"]

            node = RootNode(self.team, self.user)
            state = AssistantState(messages=[HumanMessage(content="Test")])
            config = RunnableConfig(configurable={})

            result = await node._get_context_prompts(state, config)

            # Verify both prompts are included
            self.assertEqual(result, ["Contextual tools prompt", "UI context prompt"])

            # Verify methods were called
            mock_contextual_tools.assert_called_once_with(config)
            mock_get_ui.assert_called_once_with(state)
            mock_format_ui.assert_called_once_with(MaxUIContext(), config)
            mock_dedupe.assert_called_once_with(state, ["Contextual tools prompt", "UI context prompt"])

    async def test_get_context_prompts_with_only_contextual_tools(self):
        """Test that context prompts work when only contextual tools are present"""
        with (
            patch.object(RootNode, "_get_contextual_tools_prompt") as mock_contextual_tools,
            patch.object(RootNode, "_format_ui_context") as mock_format_ui,
            patch.object(RootNode, "_get_ui_context") as mock_get_ui,
            patch.object(RootNode, "_deduplicate_context_messages") as mock_dedupe,
        ):
            # Setup mocks - only contextual tools, no UI context
            mock_contextual_tools.return_value = "Contextual tools prompt"
            mock_format_ui.return_value = None  # No UI context
            mock_get_ui.return_value = MaxUIContext()
            mock_dedupe.return_value = ["Contextual tools prompt"]

            node = RootNode(self.team, self.user)
            state = AssistantState(messages=[HumanMessage(content="Test")])
            config = RunnableConfig(configurable={})

            result = await node._get_context_prompts(state, config)

            # Should only include contextual tools prompt
            self.assertEqual(result, ["Contextual tools prompt"])
            mock_dedupe.assert_called_once_with(state, ["Contextual tools prompt"])

    def test_is_first_turn_true(self):
        """Test _is_first_turn returns True when last message is the start message"""
        node = RootNode(self.team, self.user)

        # Create state where the last message is the first human message
        state = AssistantState(
            messages=[
                HumanMessage(content="First message", id="1"),
            ]
        )

        result = node._is_first_turn(state)
        self.assertTrue(result)

    def test_is_first_turn_false_with_conversation(self):
        """Test _is_first_turn returns False when there's been conversation"""
        node = RootNode(self.team, self.user)

        # Create state with conversation history
        state = AssistantState(
            messages=[
                HumanMessage(content="First message", id="1"),
                AssistantMessage(content="Response", id="2"),
                HumanMessage(content="Second message", id="3"),
            ]
        )

        result = node._is_first_turn(state)
        self.assertFalse(result)

    def test_is_first_turn_false_with_assistant_message_last(self):
        """Test _is_first_turn returns False when last message is not human"""
        node = RootNode(self.team, self.user)

        # Create state where last message is assistant message
        state = AssistantState(
            messages=[
                HumanMessage(content="First message", id="1"),
                AssistantMessage(content="Response", id="2"),
            ]
        )

        result = node._is_first_turn(state)
        self.assertFalse(result)


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

        # Test case 2: No tool call message or root tool call - should return "end"
        state_3 = AssistantState(messages=[AssistantMessage(content="Hello")])
        self.assertEqual(node.router(state_3), "end")

        # Test case 3: Has contextual tool call result - should go back to root
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
        self.assertEqual(result.root_tool_insight_type, None)  # Insight type is determined by query planner node

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
            "products.replay.backend.max_tools.SearchSessionRecordingsTool._arun_impl",
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
        self.assertFalse(
            cast(AssistantToolCallMessage, result.messages[-1]).visible
        )  # This tool must not be visible by default

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
            mock_tools.return_value = lambda *args, **kwargs: mock_navigate_tool

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

    @patch("ee.hogai.graph.root.nodes.capture_exception")
    async def test_navigate_tool_error_does_not_raise_node_interrupt(self, mock_capture_exception):
        """Test that navigate tool errors don't raise NodeInterrupt but return FailureMessage"""
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
            # Mock the navigate tool to raise an exception
            mock_navigate_tool = AsyncMock()
            mock_navigate_tool.ainvoke = AsyncMock(side_effect=Exception("Navigation failed"))
            mock_navigate_tool.show_tool_call_message = True
            mock_navigate_tool._state = state
            mock_tools.return_value = lambda *args, **kwargs: mock_navigate_tool

            # The navigate tool call should NOT raise NodeInterrupt when there's an error
            result = await node.arun(state, {"configurable": {"contextual_tools": {"navigate": {}}}})

            # Verify capture_exception was called
            mock_capture_exception.assert_called_once()
            call_args = mock_capture_exception.call_args
            self.assertIsInstance(call_args[0][0], Exception)
            self.assertEqual(call_args[0][0].args[0], "Navigation failed")

            # Verify result is a PartialAssistantState with AssistantToolCallMessage
            self.assertIsInstance(result, PartialAssistantState)
            self.assertEqual(len(result.messages), 1)
            failure_message = result.messages[0]
            assert isinstance(failure_message, AssistantToolCallMessage)
            self.assertEqual(
                failure_message.content,
                "The tool raised an internal error. Do not immediately retry the tool call and explain to the user what happened. If the user asks you to retry, you are allowed to do that.",
            )
            self.assertEqual(result.root_tool_calls_count, 1)

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
            mock_tools.return_value = lambda *args, **kwargs: mock_search_session_recordings

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

    def test_billing_tool_routing(self):
        """Test that billing tool calls are routed correctly"""
        node = RootNodeTools(self.team, self.user)

        # Create state with billing tool call
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Let me check your billing information",
                    tool_calls=[AssistantToolCall(id="billing-123", name="retrieve_billing_information", args={})],
                )
            ],
            root_tool_call_id="billing-123",
        )

        # Should route to billing
        self.assertEqual(node.router(state), "billing")


class TestRootNodeUIContextMixin(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.mixin = RootNode(self.team, self.user)  # Using RootNode since it inherits from RootNodeUIContextMixin

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor")
    async def test_run_and_format_insight_trends_query(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.arun_and_format_query = AsyncMock(return_value=("Trend results: 100 users", None))

        insight = MaxInsightContext(
            id="123",
            name="User Trends",
            description="Daily active users",
            query=TrendsQuery(series=[EventsNode(event="pageview")]),
        )

        result = await self.mixin._arun_and_format_insight({}, insight, mock_query_runner, heading="#")
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
        mock_query_runner.arun_and_format_query.assert_called_once()

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor")
    async def test_run_and_format_insight_funnel_query(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.arun_and_format_query = AsyncMock(return_value=("Funnel results: 50% conversion", None))

        insight = MaxInsightContext(
            id="456",
            name="Conversion Funnel",
            description=None,
            query=FunnelsQuery(series=[EventsNode(event="sign_up"), EventsNode(event="purchase")]),
        )

        result = await self.mixin._arun_and_format_insight({}, insight, mock_query_runner, heading="#")

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
    async def test_run_and_format_insight_retention_query(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.arun_and_format_query = AsyncMock(return_value=("Retention: 30% Day 7", None))

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

        result = await self.mixin._arun_and_format_insight({}, insight, mock_query_runner, heading="#")
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
    async def test_run_and_format_insight_hogql_query(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.arun_and_format_query = AsyncMock(return_value=("Query results: 42 events", None))

        insight = MaxInsightContext(
            id="101",
            name="Custom Query",
            description="HogQL analysis",
            query=HogQLQuery(query="SELECT count() FROM events"),
        )

        result = await self.mixin._arun_and_format_insight({}, insight, mock_query_runner, heading="#")
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

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor", return_value=AsyncMock())
    async def test_run_and_format_insight_unsupported_query_kind(self, mock_query_runner):
        insight = MaxInsightContext(id="123", name="Unsupported", description=None, query=LifecycleQuery(series=[]))

        result = await self.mixin._arun_and_format_insight({}, insight, mock_query_runner)

        self.assertEqual(result, None)
        mock_query_runner.arun_and_format_query.assert_not_called()

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor")
    async def test_run_and_format_insight_exception_handling(self, mock_query_runner):
        mock_query_runner.arun_and_format_query = AsyncMock(side_effect=Exception("Query failed"))

        insight = MaxInsightContext(
            id="123",
            name="Failed Query",
            description=None,
            query=TrendsQuery(series=[EventsNode(event="pageview")]),
        )

        result = await self.mixin._arun_and_format_insight({}, insight, mock_query_runner)

        self.assertEqual(result, None)

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor")
    async def test_format_ui_context_with_dashboard(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.arun_and_format_query = AsyncMock(return_value=("Dashboard insight results", None))

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

        result = await self.mixin._format_ui_context(ui_context, {})

        self.assertIsNotNone(result)
        assert result is not None  # Type guard for mypy
        self.assertIn("Dashboard: Test Dashboard", result)
        self.assertIn("Description: Test dashboard description", result)
        self.assertIn("### Dashboard insights", result)
        self.assertIn("Insight: Dashboard Insight", result)
        self.assertNotIn("# Insights", result)

    async def test_format_ui_context_with_events(self):
        # Create mock events
        event1 = MaxEventContext(id="1", name="page_view")
        event2 = MaxEventContext(id="2", name="button_click")

        # Create mock UI context
        ui_context = MaxUIContext(dashboards=None, insights=None, events=[event1, event2], actions=None)

        result = await self.mixin._format_ui_context(ui_context, {})

        self.assertIsNotNone(result)
        assert result is not None  # Type guard for mypy
        self.assertIn('"page_view", "button_click"', result)
        self.assertIn("<events_context>", result)

    async def test_format_ui_context_with_events_with_descriptions(self):
        # Create mock events with descriptions
        event1 = MaxEventContext(id="1", name="page_view", description="User viewed a page")
        event2 = MaxEventContext(id="2", name="button_click", description="User clicked a button")

        # Create mock UI context
        ui_context = MaxUIContext(dashboards=None, insights=None, events=[event1, event2], actions=None)

        result = await self.mixin._format_ui_context(ui_context, {})

        self.assertIsNotNone(result)
        assert result is not None  # Type guard for mypy
        self.assertIn('"page_view: User viewed a page", "button_click: User clicked a button"', result)
        self.assertIn("<events_context>", result)

    async def test_format_ui_context_with_actions(self):
        # Create mock actions
        action1 = MaxActionContext(id=1.0, name="Sign Up")
        action2 = MaxActionContext(id=2.0, name="Purchase")

        # Create mock UI context
        ui_context = MaxUIContext(dashboards=None, insights=None, events=None, actions=[action1, action2])

        result = await self.mixin._format_ui_context(ui_context, {})

        self.assertIsNotNone(result)
        assert result is not None  # Type guard for mypy
        self.assertIn('"Sign Up", "Purchase"', result)
        self.assertIn("<actions_context>", result)

    async def test_format_ui_context_with_actions_with_descriptions(self):
        # Create mock actions with descriptions
        action1 = MaxActionContext(id=1.0, name="Sign Up", description="User creates account")
        action2 = MaxActionContext(id=2.0, name="Purchase", description="User makes a purchase")

        # Create mock UI context
        ui_context = MaxUIContext(dashboards=None, insights=None, events=None, actions=[action1, action2])

        result = await self.mixin._format_ui_context(ui_context, {})

        self.assertIsNotNone(result)
        assert result is not None  # Type guard for mypy
        self.assertIn('"Sign Up: User creates account", "Purchase: User makes a purchase"', result)
        self.assertIn("<actions_context>", result)

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor")
    async def test_format_ui_context_with_standalone_insights(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.arun_and_format_query = AsyncMock(return_value=("Standalone insight results", None))

        # Create mock insight
        insight = MaxInsightContext(
            id="123",
            name="Standalone Insight",
            description="Test standalone insight",
            query=FunnelsQuery(series=[EventsNode(event="sign_up")]),
        )

        # Create mock UI context
        ui_context = MaxUIContext(insights=[insight])

        result = await self.mixin._format_ui_context(ui_context, {})

        self.assertIsNotNone(result)
        assert result is not None  # Type guard for mypy
        self.assertIn("Insights", result)
        self.assertIn("Insight: Standalone Insight", result)
        self.assertNotIn("# Dashboards", result)

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor", return_value=AsyncMock())
    async def test_run_insights_from_ui_context_empty(self, mock_query_runner_class):
        result = await self.mixin._format_ui_context(None, {})
        self.assertEqual(result, "")

        # Test with ui_context but no insights
        ui_context = MaxUIContext(insights=None)
        result = await self.mixin._format_ui_context(ui_context, {})
        self.assertIsNone(result)

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor")
    async def test_run_insights_from_ui_context_with_insights(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.arun_and_format_query = AsyncMock(return_value=("Insight execution results", None))

        # Create mock insight
        insight = MaxInsightContext(
            id="123",
            name="Test Insight",
            description="Test description",
            query=TrendsQuery(series=[EventsNode(event="pageview")]),
        )

        # Create mock UI context
        ui_context = MaxUIContext(insights=[insight])

        result = await self.mixin._format_ui_context(ui_context, {})

        self.assertIsNotNone(result)
        result = cast(str, result)  # Type cast for mypy
        self.assertIn("# Insights", result)
        self.assertIn("Test Insight", result)
        self.assertIn("Test description", result)
        self.assertIn("Insight execution results", result)

    @patch("ee.hogai.graph.root.nodes.AssistantQueryExecutor")
    async def test_run_insights_from_ui_context_with_failed_insights(self, mock_query_runner_class):
        mock_query_runner = mock_query_runner_class.return_value
        mock_query_runner.arun_and_format_query = AsyncMock(side_effect=Exception("Query failed"))

        # Create mock insight that will fail
        insight = MaxInsightContext(
            id="123",
            name="Failed Insight",
            description=None,
            query=TrendsQuery(series=[]),
        )

        # Create mock UI context
        ui_context = MaxUIContext(insights=[insight])

        result = await self.mixin._format_ui_context(ui_context, {})

        # Should return empty string since the insight failed to run
        self.assertIsNone(result)

    @patch("posthoganalytics.feature_enabled")
    def test_session_summarization_tool_included_with_feature_flag(self, mock_feature_enabled):
        """Test that session_summarization tool is included when feature flag is enabled"""

        def feature_enabled_side_effect(flag_name, *args, **kwargs):
            if flag_name == "max-session-summarization":
                return True
            return False

        mock_feature_enabled.side_effect = feature_enabled_side_effect

        with patch("ee.hogai.graph.root.nodes.MaxChatAnthropic") as mock_chat_openai:
            mock_model = MagicMock()
            mock_model.get_num_tokens_from_messages.return_value = 100
            mock_model.bind_tools.return_value = mock_model
            mock_chat_openai.return_value = mock_model

            node = RootNode(self.team, self.user)
            state = AssistantState(messages=[HumanMessage(content="summarize my sessions")])

            node._get_model(state, {})

            self.assertEqual(mock_feature_enabled.call_count, 2)

            # Find the call for session summarization flag
            session_summarization_calls = [
                call for call in mock_feature_enabled.call_args_list if call[0][0] == "max-session-summarization"
            ]
            self.assertEqual(len(session_summarization_calls), 1)

            # Verify the session summarization flag was checked with correct parameters
            call_args, call_kwargs = session_summarization_calls[0]
            self.assertEqual(call_args[0], "max-session-summarization")
            self.assertEqual(call_args[1], str(self.user.distinct_id))
            self.assertEqual(call_kwargs["groups"], {"organization": str(self.team.organization_id)})
            self.assertEqual(call_kwargs["group_properties"], {"organization": {"id": str(self.team.organization_id)}})
            self.assertEqual(call_kwargs["send_feature_flag_events"], False)

            # Verify bind_tools was called with session_summarization
            mock_model.bind_tools.assert_called_once()
            tools = mock_model.bind_tools.call_args[0][0]
            tool_names = [getattr(tool, "__name__", None) or tool.__name__ for tool in tools]
            self.assertIn("session_summarization", tool_names)

    @patch("posthoganalytics.feature_enabled")
    def test_session_summarization_tool_excluded_without_feature_flag(self, mock_feature_enabled):
        """Test that session_summarization tool is excluded when feature flag is disabled"""
        mock_feature_enabled.return_value = False
        with patch("ee.hogai.graph.root.nodes.MaxChatAnthropic") as mock_chat_openai:
            mock_model = MagicMock()
            mock_model.get_num_tokens_from_messages.return_value = 100
            mock_model.bind_tools.return_value = mock_model
            mock_chat_openai.return_value = mock_model

            node = RootNode(self.team, self.user)
            state = AssistantState(messages=[HumanMessage(content="summarize my sessions")])

            node._get_model(state, {})

            self.assertEqual(mock_feature_enabled.call_count, 2)
            session_summarization_calls = [
                call for call in mock_feature_enabled.call_args_list if call[0][0] == "max-session-summarization"
            ]
            self.assertEqual(len(session_summarization_calls), 1)

            # Verify the session summarization flag was checked with correct parameters
            call_args, call_kwargs = session_summarization_calls[0]
            self.assertEqual(call_args[0], "max-session-summarization")
            self.assertEqual(call_args[1], str(self.user.distinct_id))
            self.assertEqual(call_kwargs["groups"], {"organization": str(self.team.organization_id)})
            self.assertEqual(call_kwargs["group_properties"], {"organization": {"id": str(self.team.organization_id)}})
            self.assertEqual(call_kwargs["send_feature_flag_events"], False)

            # Verify bind_tools was called without session_summarization
            mock_model.bind_tools.assert_called_once()
            tools = mock_model.bind_tools.call_args[0][0]
            tool_names = [getattr(tool, "__name__", None) or tool.__name__ for tool in tools]
            self.assertNotIn("session_summarization", tool_names)

    @patch("posthoganalytics.feature_enabled")
    def test_insight_search_tool_included_with_feature_flag(self, mock_feature_enabled):
        """Test that search_insights tool is included when feature flag is enabled"""

        def feature_enabled_side_effect(flag_name, *args, **kwargs):
            if flag_name == "max-ai-insight-search":
                return True
            return False

        mock_feature_enabled.side_effect = feature_enabled_side_effect

        with patch("ee.hogai.graph.root.nodes.MaxChatAnthropic") as mock_chat_openai:
            mock_model = MagicMock()
            mock_model.get_num_tokens_from_messages.return_value = 100
            mock_model.bind_tools.return_value = mock_model
            mock_chat_openai.return_value = mock_model

            node = RootNode(self.team, self.user)
            state = AssistantState(messages=[HumanMessage(content="search for insights")])

            node._get_model(state, {})

            self.assertEqual(mock_feature_enabled.call_count, 2)
            # Find the call for insight search flag
            insight_search_calls = [
                call for call in mock_feature_enabled.call_args_list if call[0][0] == "max-ai-insight-search"
            ]
            self.assertEqual(len(insight_search_calls), 1)

            # Verify the insight search flag was checked with correct parameters
            call_args, call_kwargs = insight_search_calls[0]
            self.assertEqual(call_args[0], "max-ai-insight-search")
            self.assertEqual(call_args[1], str(self.user.distinct_id))
            self.assertEqual(call_kwargs["groups"], {"organization": str(self.team.organization_id)})
            self.assertEqual(call_kwargs["group_properties"], {"organization": {"id": str(self.team.organization_id)}})
            self.assertEqual(call_kwargs["send_feature_flag_events"], False)

            # Verify bind_tools was called with search_insights
            mock_model.bind_tools.assert_called_once()
            tools = mock_model.bind_tools.call_args[0][0]
            tool_names = [getattr(tool, "__name__", None) or tool.__name__ for tool in tools]
            self.assertIn("search_insights", tool_names)

    @patch("posthoganalytics.feature_enabled")
    def test_insight_search_tool_excluded_without_feature_flag(self, mock_feature_enabled):
        """Test that search_insights tool is excluded when feature flag is disabled"""
        mock_feature_enabled.return_value = False
        with patch("ee.hogai.graph.root.nodes.MaxChatAnthropic") as mock_chat_openai:
            mock_model = MagicMock()
            mock_model.get_num_tokens_from_messages.return_value = 100
            mock_model.bind_tools.return_value = mock_model
            mock_chat_openai.return_value = mock_model

            node = RootNode(self.team, self.user)
            state = AssistantState(messages=[HumanMessage(content="search for insights")])

            node._get_model(state, {})

            self.assertEqual(mock_feature_enabled.call_count, 2)

            # Find the call for insight search flag
            insight_search_calls = [
                call for call in mock_feature_enabled.call_args_list if call[0][0] == "max-ai-insight-search"
            ]
            self.assertEqual(len(insight_search_calls), 1)

            # Verify the insight search flag was checked with correct parameters
            call_args, call_kwargs = insight_search_calls[0]
            self.assertEqual(call_args[0], "max-ai-insight-search")
            self.assertEqual(call_args[1], str(self.user.distinct_id))
            self.assertEqual(call_kwargs["groups"], {"organization": str(self.team.organization_id)})
            self.assertEqual(call_kwargs["group_properties"], {"organization": {"id": str(self.team.organization_id)}})
            self.assertEqual(call_kwargs["send_feature_flag_events"], False)

            # Verify bind_tools was called without session_summarization
            mock_model.bind_tools.assert_called_once()
            tools = mock_model.bind_tools.call_args[0][0]
            tool_names = [getattr(tool, "__name__", None) or tool.__name__ for tool in tools]
            self.assertNotIn("session_summarization", tool_names)

    @patch("ee.hogai.graph.root.nodes.capture_exception")
    async def test_tool_invocation_error_handling(self, mock_capture_exception):
        """Test that tool invocation errors are properly handled and return FailureMessage"""
        node = RootNodeTools(self.team, self.user)

        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Let me search for recordings",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(
                            id="search-123",
                            name="search_session_recordings",
                            args={"change": "test"},
                        )
                    ],
                )
            ]
        )

        with patch("ee.hogai.tool.get_contextual_tool_class") as mock_get_tool_class:
            # Mock the tool class to raise an exception
            mock_tool_class = AsyncMock()
            mock_tool_class.ainvoke = AsyncMock(side_effect=Exception("Tool execution failed"))
            mock_tool_class.show_tool_call_message = True
            # Set the initial state, but when exception happens, the code should use the FailureMessage path
            mock_tool_class._state = state

            # Mock get_contextual_tool_class to return a class constructor
            def MockToolClass(team, user, state):
                return mock_tool_class

            mock_get_tool_class.return_value = MockToolClass

            result = await node.arun(state, {"configurable": {"contextual_tools": {"search_session_recordings": {}}}})

            # Verify capture_exception was called
            mock_capture_exception.assert_called_once()
            call_args = mock_capture_exception.call_args
            self.assertIsInstance(call_args[0][0], Exception)
            self.assertEqual(call_args[0][0].args[0], "Tool execution failed")

            # Verify result is a PartialAssistantState with FailureMessage
            self.assertIsInstance(result, PartialAssistantState)
            self.assertEqual(len(result.messages), 1)
            failure_message = result.messages[0]
            assert isinstance(failure_message, AssistantToolCallMessage)
            self.assertEqual(
                failure_message.content,
                "The tool raised an internal error. Do not immediately retry the tool call and explain to the user what happened. If the user asks you to retry, you are allowed to do that.",
            )
            self.assertEqual(result.root_tool_calls_count, 1)
