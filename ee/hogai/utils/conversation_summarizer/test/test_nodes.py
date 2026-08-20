from typing import Any, cast

from posthog.test.base import BaseTest

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    HumanMessage as LangchainHumanMessage,
)
from parameterized import parameterized

from ee.hogai.utils.conversation_summarizer import AnthropicConversationSummarizer


def _count_cache_control(messages) -> int:
    count = 0
    for message in messages:
        content = getattr(message, "content", None)
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "cache_control" in block:
                    count += 1
    return count


class TestAnthropicConversationSummarizer(BaseTest):
    def setUp(self):
        super().setUp()
        self.summarizer = AnthropicConversationSummarizer(team=self.team, user=self.user)

    @parameterized.expand(
        [
            (
                "single_message",
                [
                    LangchainHumanMessage(
                        content=[
                            {"type": "text", "text": "Hello", "cache_control": {"type": "ephemeral"}},
                        ]
                    )
                ],
                [[{"type": "text", "text": "Hello", "cache_control": {"type": "ephemeral"}}]],
            ),
            (
                "breakpoint_moves_to_last_block",
                [
                    LangchainAIMessage(
                        content=[
                            {"type": "text", "text": "First", "cache_control": {"type": "ephemeral"}},
                            {"type": "text", "text": "Second", "cache_control": {"type": "ephemeral"}},
                        ]
                    )
                ],
                [
                    [
                        {"type": "text", "text": "First"},
                        {"type": "text", "text": "Second", "cache_control": {"type": "ephemeral"}},
                    ]
                ],
            ),
            (
                "breakpoint_moves_to_last_message",
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
                    [{"type": "text", "text": "Message 2", "cache_control": {"type": "ephemeral"}}],
                ],
            ),
        ]
    )
    def test_reanchors_a_single_cache_breakpoint_at_the_end(self, name, input_messages, expected_contents):
        # A revert to stripping every breakpoint without re-anchoring one — which billed the whole
        # summarization prompt as uncached input every time — fails this test.
        result = self.summarizer._construct_messages(input_messages)
        messages = result.messages[1:-1]  # Skip the system prompt and the trailing user prompt

        self.assertEqual(_count_cache_control(messages), 1, f"Expected exactly one breakpoint in: {name}")
        for i, (message, expected_content) in enumerate(zip(messages, expected_contents)):
            self.assertEqual(message.content, expected_content, f"Message {i} mismatch in: {name}")

    def test_breakpoint_skips_blocks_anthropic_rejects_it_on(self):
        # A cache_control marker on a thinking or tool_use block is rejected by Anthropic, so the
        # breakpoint must land on the preceding text block, not the trailing thinking block.
        input_messages = [
            LangchainHumanMessage(content=[{"type": "text", "text": "Question"}]),
            LangchainAIMessage(content=[{"type": "thinking", "thinking": "reasoning", "signature": "sig"}]),
        ]

        result = self.summarizer._construct_messages(input_messages)
        human_block, thinking_block = (m.content[0] for m in result.messages[1:-1])

        self.assertIn("cache_control", human_block)
        self.assertNotIn("cache_control", thinking_block)

    def test_string_content_becomes_a_cached_text_block(self):
        result = self.summarizer._construct_messages([LangchainHumanMessage(content="Simple string")])
        block = result.messages[1].content[0]
        self.assertEqual(block, {"type": "text", "text": "Simple string", "cache_control": {"type": "ephemeral"}})

    @parameterized.expand(
        [
            ("empty_list_content", [LangchainHumanMessage(content=[])]),
            ("non_dict_items_in_list", [LangchainHumanMessage(content=["string_item"])]),
        ]
    )
    def test_handles_uncacheable_content_without_errors(self, name, input_messages):
        result = self.summarizer._construct_messages(input_messages)
        self.assertEqual(_count_cache_control(result.messages), 0)

    def test_original_message_not_modified(self):
        original_content: list[str | dict[Any, Any]] = [
            {"type": "text", "text": "Hello", "cache_control": {"type": "ephemeral"}, "other_key": "value"},
        ]
        message = LangchainHumanMessage(content=original_content)

        self.summarizer._construct_messages([message])

        content_list = cast(list[dict[str, Any]], message.content)
        self.assertEqual(set(content_list[0].keys()), {"type", "text", "cache_control", "other_key"})
        self.assertEqual(content_list[0]["cache_control"], {"type": "ephemeral"})

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
            ),
            LangchainHumanMessage(content=[{"type": "text", "text": "Latest"}]),
        ]

        result = self.summarizer._construct_messages(input_messages)
        first_block = result.messages[1].content[0]

        self.assertEqual(first_block["custom_field"], "custom_value")
        self.assertEqual(first_block["another_field"], 123)
        self.assertNotIn("cache_control", first_block)

    def test_empty_messages_list(self):
        result = self.summarizer._construct_messages([])
        # Only the system and user prompts remain, and neither carries a transcript breakpoint.
        self.assertEqual(len(result.messages), 2)
