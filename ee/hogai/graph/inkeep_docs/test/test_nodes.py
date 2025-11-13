from typing import cast
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    HumanMessage as LangchainHumanMessage,
    SystemMessage as LangchainSystemMessage,
    ToolMessage as LangchainToolMessage,
)
from langchain_core.runnables import RunnableLambda

from posthog.schema import AssistantMessage, AssistantToolCall, AssistantToolCallMessage, HumanMessage

from ee.hogai.graph.inkeep_docs.nodes import InkeepDocsNode
from ee.hogai.graph.inkeep_docs.prompts import INKEEP_DATA_CONTINUATION_PHRASE
from ee.hogai.utils.types import AssistantState, PartialAssistantState


class TestInkeepDocsNode(ClickhouseTestMixin, BaseTest):
    async def test_node_handles_plain_response(self):
        test_tool_call_id = str(uuid4())
        with patch(
            "ee.hogai.graph.inkeep_docs.nodes.InkeepDocsNode._get_model",
            return_value=RunnableLambda(
                lambda _: LangchainAIMessage(content="Here's what I found in the documentation...")
            ),
        ):
            node = InkeepDocsNode(self.team, self.user)
            state = AssistantState(
                messages=[HumanMessage(content="How do I use feature flags?")],
                root_tool_call_id=test_tool_call_id,
            )
            next_state = await node.arun(state, {})
            self.assertIsInstance(next_state, PartialAssistantState)
            assert next_state is not None
            messages = cast(list, next_state.messages)
            self.assertEqual(len(messages), 2)

            # First message should be a tool call message
            first_message = cast(AssistantToolCallMessage, messages[0])
            self.assertIsInstance(first_message, AssistantToolCallMessage)
            self.assertEqual(first_message.content, "Checking PostHog documentation...")
            self.assertEqual(first_message.tool_call_id, test_tool_call_id)

            # Second message should be the actual response
            second_message = cast(AssistantMessage, messages[1])
            self.assertIsInstance(second_message, AssistantMessage)
            self.assertEqual(second_message.content, "Here's what I found in the documentation...")

    async def test_node_handles_response_with_data_continuation(self):
        test_tool_call_id = str(uuid4())
        response_with_continuation = f"Here's what I found... {INKEEP_DATA_CONTINUATION_PHRASE}"
        with patch(
            "ee.hogai.graph.inkeep_docs.nodes.InkeepDocsNode._get_model",
            return_value=RunnableLambda(lambda _: LangchainAIMessage(content=response_with_continuation)),
        ):
            node = InkeepDocsNode(self.team, self.user)
            state = AssistantState(
                messages=[HumanMessage(content="Show me user stats")],
                root_tool_call_id=test_tool_call_id,
            )
            next_state = await node.arun(state, {})
            self.assertIsInstance(next_state, PartialAssistantState)
            assert next_state is not None
            messages = cast(list, next_state.messages)
            self.assertEqual(len(messages), 2)
            # Tool call message should have the continuation prompt
            first_message = cast(AssistantToolCallMessage, messages[0])
            self.assertIn("Continue with the user's data request", first_message.content)
            second_message = cast(AssistantMessage, messages[1])
            self.assertEqual(second_message.content, response_with_continuation)

    def test_node_constructs_messages(self):
        node = InkeepDocsNode(self.team, self.user)
        state = AssistantState(
            messages=[
                HumanMessage(content="First message"),
                AssistantMessage(content="Hi!"),
                HumanMessage(content="How do I use PostHog?"),
                AssistantMessage(content="Let me check the docs..."),
            ]
        )
        messages = node._construct_messages(
            state.messages, state.root_conversation_start_id, state.root_tool_calls_count
        )

        # Should not include "Let me check the docs...", because Inkeep would fail with the last message being an AI one
        self.assertEqual(len(messages), 4)
        self.assertIsInstance(messages[0], LangchainSystemMessage)
        self.assertIsInstance(messages[1], LangchainHumanMessage)
        self.assertIsInstance(messages[2], LangchainAIMessage)
        self.assertIsInstance(messages[3], LangchainHumanMessage)

    async def test_tool_call_id_handling(self):
        """Test that tool_call_id is properly handled in both input and output states."""
        test_tool_call_id = str(uuid4())
        with patch(
            "ee.hogai.graph.inkeep_docs.nodes.InkeepDocsNode._get_model",
            return_value=RunnableLambda(lambda _: LangchainAIMessage(content="Response")),
        ):
            node = InkeepDocsNode(self.team, self.user)
            state = AssistantState(
                messages=[HumanMessage(content="Question")],
                root_tool_call_id=test_tool_call_id,
            )
            next_state = await node.arun(state, {})
            assert next_state is not None

            # Check that the tool call message uses the input tool_call_id
            messages = cast(list, next_state.messages)
            first_message = cast(AssistantToolCallMessage, messages[0])
            self.assertEqual(first_message.tool_call_id, test_tool_call_id)

            # Check that the output state resets tool_call_id
            self.assertEqual(next_state.root_tool_call_id, None)

    async def test_message_id_generation(self):
        """Test that each message gets a unique UUID."""
        with patch(
            "ee.hogai.graph.inkeep_docs.nodes.InkeepDocsNode._get_model",
            return_value=RunnableLambda(lambda _: LangchainAIMessage(content="Response")),
        ):
            node = InkeepDocsNode(self.team, self.user)
            state = AssistantState(
                messages=[HumanMessage(content="Question")],
                root_tool_call_id="test-id",
            )
            next_state = await node.arun(state, {})
            assert next_state is not None
            messages = cast(list, next_state.messages)

            # Check that both messages have IDs and they're different
            first_message = cast(AssistantToolCallMessage, messages[0])
            second_message = cast(AssistantMessage, messages[1])
            self.assertIsNotNone(first_message.id)
            self.assertIsNotNone(second_message.id)
            self.assertNotEqual(first_message.id, second_message.id)

    def test_truncates_messages_after_limit(self):
        """Inkeep accepts maximum 30 messages"""
        node = InkeepDocsNode(self.team, self.user)
        state = AssistantState(
            messages=[HumanMessage(content=str(i)) for i in range(31)],
            root_tool_call_id="test-id",
        )
        next_state = node._construct_messages(
            state.messages, state.root_conversation_start_id, state.root_tool_calls_count
        )
        self.assertEqual(len(next_state), 29)
        self.assertEqual(next_state[0].type, "system")
        self.assertEqual(next_state[1].content, "3")
        self.assertEqual(next_state[-1].content, "30")

    def test_filters_out_empty_ai_messages(self):
        node = InkeepDocsNode(self.team, self.user)
        state = AssistantState(
            messages=[
                HumanMessage(content="First message"),
                AssistantMessage(content=""),
                HumanMessage(content="Second message"),
                AssistantMessage(content="", tool_calls=[AssistantToolCall(id="1", name="test", args={})]),
                AssistantToolCallMessage(content="Tool", tool_call_id="1"),
                HumanMessage(content="Third message"),
                AssistantMessage(content="Valid response"),
            ]
        )
        messages = node._construct_messages(
            state.messages, state.root_conversation_start_id, state.root_tool_calls_count
        )

        # Last message must be truncated
        self.assertEqual(len(messages), 7)
        self.assertIsInstance(messages[0], LangchainSystemMessage)
        self.assertIsInstance(messages[1], LangchainHumanMessage)
        self.assertEqual(messages[1].content, "First message")
        self.assertIsInstance(messages[2], LangchainAIMessage)
        self.assertEqual(messages[2].content, "...")
        self.assertIsInstance(messages[3], LangchainHumanMessage)
        self.assertEqual(messages[3].content, "Second message")
        assert isinstance(messages[4], LangchainAIMessage)
        self.assertEqual(messages[4].content, "...")
        self.assertIsNotNone(messages[4].tool_calls)
        self.assertIsInstance(messages[5], LangchainToolMessage)
        self.assertEqual(messages[5].content, "Tool")
        self.assertIsInstance(messages[6], LangchainHumanMessage)
        self.assertEqual(messages[6].content, "Third message")
