from typing import Any, cast

from django.test import SimpleTestCase

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    HumanMessage as LangchainHumanMessage,
)
from parameterized import parameterized

from ee.hogai.utils.conversation_summarizer.input_budget import ConversationInputBudget


def _tool_result(text: str, tool_use_id: str = "call_1") -> LangchainHumanMessage:
    return LangchainHumanMessage(content=[{"type": "tool_result", "tool_use_id": tool_use_id, "content": text}])


def _text_message(text: str) -> LangchainHumanMessage:
    return LangchainHumanMessage(content=[{"type": "text", "text": text}])


class TestConversationInputBudget(SimpleTestCase):
    def _chars(self, messages) -> int:
        return ConversationInputBudget(1)._count_chars(messages)

    @parameterized.expand(
        [
            ("string_content", [LangchainHumanMessage(content="a" * 100)]),
            ("text_block", [_text_message("a" * 100)]),
            ("tool_result_block", [_tool_result("a" * 100)]),
        ]
    )
    def test_leaves_a_conversation_inside_the_budget_alone(self, _name, messages):
        result = ConversationInputBudget(1_000).apply(messages)

        self.assertEqual([message.content for message in result], [message.content for message in messages])

    @parameterized.expand(
        [
            ("string_content", [LangchainHumanMessage(content="a" * 40_000)]),
            ("text_block", [_text_message("a" * 40_000)]),
            ("tool_result_block", [_tool_result("a" * 40_000)]),
            (
                "one_oversized_message_among_many",
                [_text_message("short"), _tool_result("a" * 40_000), _text_message("also short")],
            ),
            ("many_oversized_messages", [_tool_result("a" * 20_000, f"call_{i}") for i in range(5)]),
        ]
    )
    def test_brings_an_oversized_conversation_inside_the_budget(self, _name, messages):
        budget = ConversationInputBudget(1_000)

        result = budget.apply(messages)

        self.assertLessEqual(self._chars(result), 1_000 * ConversationInputBudget.APPROXIMATE_TOKEN_LENGTH)
        self.assertEqual(len(result), len(messages))

    def test_spends_the_budget_on_the_small_messages_first(self):
        messages = [_text_message("keep me"), _tool_result("a" * 40_000)]

        result = ConversationInputBudget(1_000).apply(messages)

        self.assertEqual(cast(list[dict[str, Any]], result[0].content)[0]["text"], "keep me")
        self.assertLess(len(cast(list[dict[str, Any]], result[1].content)[0]["content"]), 40_000)

    def test_keeps_the_tool_result_block_addressable(self):
        result = ConversationInputBudget(100).apply([_tool_result("a" * 40_000, "call_42")])

        block = cast(list[dict[str, Any]], result[0].content)[0]
        self.assertEqual(block["type"], "tool_result")
        self.assertEqual(block["tool_use_id"], "call_42")
        self.assertIn(ConversationInputBudget.TRUNCATION_NOTICE, block["content"])

    def test_does_not_shorten_a_thinking_block(self):
        # Anthropic validates a thinking signature against the exact text it returned, so a
        # shortened thinking block is rejected outright.
        thinking = {"type": "thinking", "thinking": "b" * 5_000, "signature": "sig"}
        messages = [LangchainAIMessage(content=[thinking, {"type": "text", "text": "a" * 40_000}])]

        result = ConversationInputBudget(1_000).apply(messages)

        self.assertEqual(cast(list[dict[str, Any]], result[0].content)[0], thinking)

    def test_does_not_shorten_tool_call_arguments(self):
        # Truncated arguments are no longer parseable JSON.
        tool_calls = [{"name": "query", "args": {"sql": "c" * 5_000}, "id": "call_1", "type": "tool_call"}]
        messages = [
            LangchainAIMessage(content=[{"type": "text", "text": "a" * 40_000}], tool_calls=tool_calls),
            _tool_result("result", "call_1"),
        ]

        result = ConversationInputBudget(1_000).apply(messages)

        self.assertEqual(cast(LangchainAIMessage, result[0]).tool_calls, tool_calls)

    def test_does_not_mutate_the_messages_it_was_given(self):
        messages = [_tool_result("a" * 40_000), LangchainHumanMessage(content="b" * 40_000)]

        ConversationInputBudget(100).apply(messages)

        self.assertEqual(cast(list[dict[str, Any]], messages[0].content)[0]["content"], "a" * 40_000)
        self.assertEqual(messages[1].content, "b" * 40_000)

    def test_fits_a_conversation_whose_untruncatable_content_alone_exceeds_the_budget(self):
        # A budget this small cannot be met, but the call still has to return a usable
        # conversation rather than raise or loop.
        messages = [
            LangchainAIMessage(content=[{"type": "thinking", "thinking": "b" * 5_000, "signature": "sig"}]),
            _tool_result("a" * 40_000),
        ]

        result = ConversationInputBudget(10).apply(messages)

        self.assertEqual(len(result), 2)
        self.assertEqual(cast(list[dict[str, Any]], result[1].content)[0]["content"], "")
