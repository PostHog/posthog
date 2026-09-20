from django.test import SimpleTestCase

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from posthog.temporal.ai_observability.eval_reports.report_agent.context_window import (
    CHARS_PER_TOKEN,
    MAX_PROMPT_TOKENS,
    MAX_TOOL_RESULT_TOKENS,
    TOOL_RESULT_TRUNCATED_NOTE,
    trim_agent_messages,
)


def _turn(index: int, payload: str) -> list:
    call_id = f"call-{index}"
    return [
        AIMessage(content="", tool_calls=[{"name": "get_trace_detail", "args": {}, "id": call_id}]),
        ToolMessage(content=payload, tool_call_id=call_id),
    ]


def _prompt_chars(messages: list) -> int:
    return sum(len(str(message.content)) for message in messages)


class TestTrimAgentMessages(SimpleTestCase):
    def test_short_history_passes_through_unchanged(self):
        messages = [HumanMessage(content="Please generate the evaluation report."), *_turn(0, "a small result")]

        self.assertEqual(trim_agent_messages({"messages": messages})["llm_input_messages"], messages)

    def test_oversized_tool_result_is_capped_and_says_so(self):
        payload = "x" * (int(MAX_TOOL_RESULT_TOKENS * CHARS_PER_TOKEN) * 3)
        messages = [HumanMessage(content="Please generate the evaluation report."), *_turn(0, payload)]

        trimmed = trim_agent_messages({"messages": messages})["llm_input_messages"]

        self.assertEqual(len(trimmed), 3)
        capped = trimmed[2].content
        assert isinstance(capped, str)
        self.assertTrue(capped.endswith(TOOL_RESULT_TRUNCATED_NOTE))
        self.assertLess(len(capped), len(payload))
        # The state keeps the full result; only what goes to the model is capped.
        self.assertEqual(messages[2].content, payload)

    def test_accumulated_history_is_trimmed_to_the_prompt_budget(self):
        payload = "x" * int(MAX_TOOL_RESULT_TOKENS * CHARS_PER_TOKEN)
        messages = [HumanMessage(content="Please generate the evaluation report.")]
        for index in range(20):
            messages.extend(_turn(index, payload))

        trimmed = trim_agent_messages({"messages": messages})["llm_input_messages"]

        self.assertLessEqual(_prompt_chars(trimmed) / CHARS_PER_TOKEN, MAX_PROMPT_TOKENS)
        self.assertIs(trimmed[0], messages[0])
        self.assertIs(trimmed[-1], messages[-1])

    def test_trim_never_leaves_a_tool_result_without_its_request(self):
        payload = "x" * int(MAX_TOOL_RESULT_TOKENS * CHARS_PER_TOKEN)
        messages = [HumanMessage(content="Please generate the evaluation report.")]
        for index in range(20):
            messages.extend(_turn(index, payload))

        trimmed = trim_agent_messages({"messages": messages})["llm_input_messages"]

        answered_call_ids = {
            tool_call["id"] for message in trimmed if isinstance(message, AIMessage) for tool_call in message.tool_calls
        }
        orphans = [
            message
            for message in trimmed
            if isinstance(message, ToolMessage) and message.tool_call_id not in answered_call_ids
        ]
        self.assertEqual(orphans, [])
