from typing import cast
from unittest.mock import MagicMock, patch
from uuid import uuid4

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    HumanMessage as LangchainHumanMessage,
    SystemMessage as LangchainSystemMessage,
)
from langchain_core.runnables import RunnableLambda

from ee.hogai.graph.inkeep_docs.nodes import InkeepDocsNode
from ee.hogai.graph.inkeep_docs.prompts import INKEEP_DATA_CONTINUATION_PHRASE
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantMessage, AssistantToolCallMessage, HumanMessage
from posthog.test.base import BaseTest, ClickhouseTestMixin


class TestInkeepDocsNode(ClickhouseTestMixin, BaseTest):
    def test_node_handles_plain_response(self):
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
            next_state = node.run(state, {})
            self.assertIsInstance(next_state, PartialAssistantState)
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

    def test_node_handles_response_with_data_continuation(self):
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
            next_state = node.run(state, {})
            self.assertIsInstance(next_state, PartialAssistantState)
            messages = cast(list, next_state.messages)
            self.assertEqual(len(messages), 2)
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
        messages = node._construct_messages(state)

        # Should not include "Let me check the docs...", because Inkeep would fail with the last message being an AI one
        self.assertEqual(len(messages), 4)
        self.assertIsInstance(messages[0], LangchainSystemMessage)
        self.assertIsInstance(messages[1], LangchainHumanMessage)
        self.assertIsInstance(messages[2], LangchainAIMessage)
        self.assertIsInstance(messages[3], LangchainHumanMessage)

    def test_router_with_data_continuation(self):
        node = InkeepDocsNode(self.team, self.user)
        state = AssistantState(
            messages=[
                HumanMessage(content="Explain PostHog trends, and show me an example trends insight"),
                AssistantMessage(content=f"Here's the documentation: XYZ.\n{INKEEP_DATA_CONTINUATION_PHRASE}"),
            ]
        )
        self.assertEqual(node.router(state), "root")  # Going back to root, so that the agent can continue with the task

    def test_router_without_data_continuation(self):
        node = InkeepDocsNode(self.team, self.user)
        state = AssistantState(
            messages=[
                HumanMessage(content="How do I use feature flags?"),
                AssistantMessage(content="Here's how to use feature flags..."),
            ]
        )
        self.assertEqual(node.router(state), "end")  # Ending

    def test_node_filters_empty_messages(self):
        """Test that messages with empty content are filtered out during message construction."""
        node = InkeepDocsNode(self.team, self.user)
        state = AssistantState(
            messages=[
                HumanMessage(content=""),  # Empty message that should be filtered
                AssistantMessage(content="Hi!"),
                HumanMessage(content="How do I use PostHog?"),
                AssistantMessage(content=""),  # Empty message that should be filtered
            ]
        )
        messages = node._construct_messages(state)

        # Should only include system message, "Hi!", and "How do I use PostHog?"
        self.assertEqual(len(messages), 3)
        self.assertIsInstance(messages[0], LangchainSystemMessage)
        self.assertEqual(messages[1].content, "Hi!")
        self.assertEqual(messages[2].content, "How do I use PostHog?")

    def test_tool_call_id_handling(self):
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
            next_state = node.run(state, {})

            # Check that the tool call message uses the input tool_call_id
            messages = cast(list, next_state.messages)
            first_message = cast(AssistantToolCallMessage, messages[0])
            self.assertEqual(first_message.tool_call_id, test_tool_call_id)

            # Check that the output state resets tool_call_id
            self.assertEqual(next_state.root_tool_call_id, "")

    def test_message_id_generation(self):
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
            next_state = node.run(state, {})
            messages = cast(list, next_state.messages)

            # Check that both messages have IDs and they're different
            first_message = cast(AssistantToolCallMessage, messages[0])
            second_message = cast(AssistantMessage, messages[1])
            self.assertIsNotNone(first_message.id)
            self.assertIsNotNone(second_message.id)
            self.assertNotEqual(first_message.id, second_message.id)

    def test_model_has_correct_max_retries(self) -> None:
        with patch("ee.hogai.graph.inkeep_docs.nodes.ChatOpenAI") as mock_chat_openai:
            mock_model = MagicMock()
            mock_chat_openai.return_value = mock_model

            node = InkeepDocsNode(self.team, self.user)

            node._get_model()

            mock_chat_openai.assert_called_once()
            call_args = mock_chat_openai.call_args
            self.assertEqual(call_args.kwargs["max_retries"], 3)
