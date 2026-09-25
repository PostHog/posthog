from typing import Any, cast

from posthog.test.base import BaseTest
from unittest.mock import patch

import httpx
import anthropic
from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    HumanMessage as LangchainHumanMessage,
)
from langchain_core.runnables import RunnableLambda
from parameterized import parameterized

from ee.hogai.utils.conversation_summarizer import AnthropicConversationSummarizer
from ee.hogai.utils.conversation_summarizer.input_budget import ConversationInputBudget
from ee.hogai.utils.conversation_summarizer.prompts import SUMMARIZATION_INSTRUCTION_PROMPT


def _budget_chars(messages) -> int:
    # Measure messages the way `ConversationInputBudget` spends its budget.
    return ConversationInputBudget(1)._count_chars(messages)


def _anthropic_error(message: str) -> anthropic.BadRequestError:
    return anthropic.BadRequestError(
        message=message,
        response=httpx.Response(
            status_code=400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        ),
        body={"type": "error", "error": {"type": "invalid_request_error"}},
    )


class TestAnthropicConversationSummarizer(BaseTest):
    def setUp(self):
        super().setUp()
        self.summarizer = AnthropicConversationSummarizer(team=self.team, user=self.user)

    @parameterized.expand(
        [
            (
                "single_message_with_cache_control",
                [
                    LangchainHumanMessage(
                        content=[
                            {"type": "text", "text": "Hello", "cache_control": {"type": "ephemeral"}},
                        ]
                    )
                ],
                [[{"type": "text", "text": "Hello"}]],
            ),
            (
                "multiple_items_with_cache_control",
                [
                    LangchainAIMessage(
                        content=[
                            {"type": "text", "text": "First", "cache_control": {"type": "ephemeral"}},
                            {"type": "text", "text": "Second", "cache_control": {"type": "ephemeral"}},
                        ]
                    )
                ],
                [[{"type": "text", "text": "First"}, {"type": "text", "text": "Second"}]],
            ),
            (
                "mixed_items_some_with_cache_control",
                [
                    LangchainHumanMessage(
                        content=[
                            {"type": "text", "text": "With cache", "cache_control": {"type": "ephemeral"}},
                            {"type": "text", "text": "Without cache"},
                        ]
                    )
                ],
                [[{"type": "text", "text": "With cache"}, {"type": "text", "text": "Without cache"}]],
            ),
            (
                "multiple_messages_with_cache_control",
                [
                    LangchainHumanMessage(
                        content=[
                            {"type": "text", "text": "Message 1", "cache_control": {"type": "ephemeral"}},
                        ]
                    ),
                    LangchainAIMessage(
                        content=[
                            {"type": "text", "text": "Message 2", "cache_control": {"type": "ephemeral"}},
                        ]
                    ),
                ],
                [
                    [{"type": "text", "text": "Message 1"}],
                    [{"type": "text", "text": "Message 2"}],
                ],
            ),
        ]
    )
    def test_removes_cache_control(self, name, input_messages, expected_contents):
        result = self.summarizer._construct_messages(input_messages)

        # Extract the actual messages from the prompt template
        messages = result.messages[1:-1]  # Skip system prompt and user prompt

        self.assertEqual(len(messages), len(expected_contents), f"Wrong number of messages in test case: {name}")

        for i, (message, expected_content) in enumerate(zip(messages, expected_contents)):
            self.assertEqual(
                message.content,
                expected_content,
                f"Message {i} content mismatch in test case: {name}",
            )

    @parameterized.expand(
        [
            (
                "string_content",
                [LangchainHumanMessage(content="Simple string")],
            ),
            (
                "empty_list_content",
                [LangchainHumanMessage(content=[])],
            ),
            (
                "non_dict_items_in_list",
                [LangchainHumanMessage(content=["string_item", {"type": "text", "text": "dict_item"}])],
            ),
        ]
    )
    def test_handles_non_dict_content_without_errors(self, name, input_messages):
        result = self.summarizer._construct_messages(input_messages)
        self.assertIsNotNone(result)

    def test_original_message_not_modified(self):
        original_content: list[str | dict[Any, Any]] = [
            {"type": "text", "text": "Hello", "cache_control": {"type": "ephemeral"}},
        ]
        message = LangchainHumanMessage(content=original_content)

        # Store the original cache_control to verify it's not modified
        content_list = cast(list[dict[str, Any]], message.content)
        self.assertIn("cache_control", content_list[0])

        self.summarizer._construct_messages([message])

        # Verify original message still has cache_control
        content_list = cast(list[dict[str, Any]], message.content)
        self.assertIn("cache_control", content_list[0])
        self.assertEqual(content_list[0]["cache_control"], {"type": "ephemeral"})

    def test_deep_copy_prevents_modification(self):
        original_content: list[str | dict[Any, Any]] = [
            {
                "type": "text",
                "text": "Test",
                "cache_control": {"type": "ephemeral"},
                "other_key": "value",
            },
        ]
        message = LangchainHumanMessage(content=original_content)

        content_list = cast(list[dict[str, Any]], message.content)
        original_keys = set(content_list[0].keys())

        self.summarizer._construct_messages([message])

        # Verify original message structure unchanged
        content_list = cast(list[dict[str, Any]], message.content)
        self.assertEqual(set(content_list[0].keys()), original_keys)
        self.assertIn("cache_control", content_list[0])

    def test_preserves_other_content_properties(self):
        input_messages = [
            LangchainHumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": "Hello",
                        "cache_control": {"type": "ephemeral"},
                        "custom_field": "custom_value",
                        "another_field": 123,
                    },
                ]
            )
        ]

        result = self.summarizer._construct_messages(input_messages)
        messages = result.messages[1:-1]

        # Verify other fields are preserved
        content = messages[0].content[0]
        self.assertEqual(content["custom_field"], "custom_value")
        self.assertEqual(content["another_field"], 123)
        self.assertNotIn("cache_control", content)

    def test_empty_messages_list(self):
        result = self.summarizer._construct_messages([])
        # Should return prompt template with just system and user prompts
        self.assertEqual(len(result.messages), 2)

    def test_only_cache_breakpoint_is_the_fixed_prefix(self):
        messages = self.summarizer._construct_messages(
            [
                LangchainHumanMessage(content=[{"type": "text", "text": "Hello"}]),
                LangchainAIMessage(content=[{"type": "text", "text": "Hi", "cache_control": {"type": "ephemeral"}}]),
            ]
        ).format_messages()

        cached = [
            (message, block)
            for message in messages
            for block in (message.content if isinstance(message.content, list) else [])
            if isinstance(block, dict) and "cache_control" in block
        ]
        self.assertEqual(len(cached), 1)
        cached_message, cached_block = cached[0]
        self.assertIs(cached_message, messages[0])
        self.assertIn(SUMMARIZATION_INSTRUCTION_PROMPT, cached_block["text"])
        self.assertEqual(cached_block["cache_control"], {"type": "ephemeral", "ttl": "1h"})

    @parameterized.expand(
        [
            ("conversation_ends_with_assistant_message", LangchainAIMessage(content="Done")),
            ("conversation_ends_with_human_message", LangchainHumanMessage(content="Thanks")),
        ]
    )
    def test_request_ends_on_a_user_turn(self, name, last_message):
        messages = self.summarizer._construct_messages([last_message]).format_messages()

        self.assertIsInstance(messages[-1], LangchainHumanMessage)

    def _stub_model(self, responses: list[Any]) -> tuple[RunnableLambda, list[int]]:
        request_sizes: list[int] = []

        def invoke(prompt_value):
            request_sizes.append(_budget_chars(prompt_value.to_messages()))
            response = responses[len(request_sizes) - 1]
            if isinstance(response, Exception):
                raise response
            return LangchainAIMessage(content=response)

        return RunnableLambda(invoke), request_sizes

    def _oversized_conversation(self) -> list[LangchainHumanMessage]:
        return [
            LangchainHumanMessage(content=[{"type": "tool_result", "tool_use_id": "call_1", "content": "a" * 100_000}])
        ]

    def _prompt_overhead(self) -> int:
        # The summarizer's own prompts sit outside the conversation budget.
        return _budget_chars(self.summarizer._construct_messages([]).format_messages())

    async def test_bounds_an_oversized_conversation_before_sending_it(self):
        model, request_sizes = self._stub_model(["<summary>Done</summary>"])
        budget_chars = 1_000 * ConversationInputBudget.APPROXIMATE_TOKEN_LENGTH

        with (
            patch.object(AnthropicConversationSummarizer, "MAX_INPUT_TOKENS", 1_000),
            patch.object(self.summarizer, "_get_model", return_value=model),
        ):
            summary = await self.summarizer.summarize(self._oversized_conversation())

        self.assertEqual(summary, "Done")
        self.assertEqual(len(request_sizes), 1)
        self.assertLessEqual(request_sizes[0], budget_chars + self._prompt_overhead())

    async def test_retries_smaller_when_the_model_rejects_the_input_as_too_long(self):
        model, request_sizes = self._stub_model(
            [
                _anthropic_error("prompt is too long: 1476968 tokens > 1000000 maximum"),
                "<summary>Done</summary>",
            ]
        )

        with (
            patch.object(AnthropicConversationSummarizer, "MAX_INPUT_TOKENS", 1_000),
            patch.object(AnthropicConversationSummarizer, "RETRY_INPUT_TOKENS", 100),
            patch.object(self.summarizer, "_get_model", return_value=model),
        ):
            summary = await self.summarizer.summarize(self._oversized_conversation())

        self.assertEqual(summary, "Done")
        self.assertEqual(len(request_sizes), 2)
        self.assertLess(request_sizes[1], request_sizes[0])

    @parameterized.expand(
        [
            ("unrelated_bad_request", _anthropic_error("messages: at least one message is required")),
            ("unrelated_error", ValueError("boom")),
        ]
    )
    async def test_does_not_retry_an_error_that_is_not_about_input_size(self, _name, error):
        model, request_sizes = self._stub_model([error])

        with patch.object(self.summarizer, "_get_model", return_value=model):
            with self.assertRaises(type(error)):
                await self.summarizer.summarize([LangchainHumanMessage(content="Hello")])

        self.assertEqual(len(request_sizes), 1)
