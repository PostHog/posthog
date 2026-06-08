from posthog.test.base import BaseTest

from posthog.schema import AssistantMessage, AssistantToolCallMessage, ContextMessage, FailureMessage, HumanMessage

from ee.hogai.utils.openai import convert_to_openai_message, convert_to_openai_messages


class TestOpenAIUtils(BaseTest):
    def test_convert_context_message_to_openai_message(self):
        message = ContextMessage(content="Context information")

        result = convert_to_openai_message(message, {})

        assert len(result) == 1
        assert result[0].content == "Context information"

    def test_convert_assistant_message_to_openai_message_without_tool_calls(self):
        message = AssistantMessage(content="Assistant response", id="asst_123", tool_calls=[])

        result = convert_to_openai_message(message, {})

        assert len(result) == 1
        assert result[0].content == "Assistant response"
        assert result[0].id == "asst_123"

    def test_convert_assistant_message_to_openai_message_with_tool_calls(self):
        message = AssistantMessage(
            content="Let me search for that",
            id="asst_456",
            tool_calls=[
                {"id": "tool_1", "name": "search", "args": {"query": "test"}},
                {"id": "tool_2", "name": "read_data", "args": {"id": 123}},
            ],
        )
        tool_result_map = {
            "tool_1": AssistantToolCallMessage(content="Search result", id="result_1", tool_call_id="tool_1"),
            "tool_2": AssistantToolCallMessage(content="Data content", id="result_2", tool_call_id="tool_2"),
        }

        result = convert_to_openai_message(message, tool_result_map)

        assert len(result) == 3
        assert result[0].content == "Let me search for that"
        assert len(result[0].tool_calls) == 2  # type: ignore
        assert result[1].content == "Search result"
        assert result[1].tool_call_id == "tool_1"  # type: ignore
        assert result[2].content == "Data content"
        assert result[2].tool_call_id == "tool_2"  # type: ignore

    def test_convert_assistant_message_filters_missing_tool_results(self):
        message = AssistantMessage(
            content="Processing",
            id="asst_789",
            tool_calls=[
                {"id": "tool_1", "name": "search", "args": {"query": "test"}},
                {"id": "tool_2", "name": "missing_tool", "args": {}},
            ],
        )
        tool_result_map = {
            "tool_1": AssistantToolCallMessage(content="Search result", id="result_1", tool_call_id="tool_1"),
        }

        result = convert_to_openai_message(message, tool_result_map)

        assert len(result) == 2
        assert len(result[0].tool_calls) == 1  # type: ignore
        assert result[0].tool_calls[0]["id"] == "tool_1"  # type: ignore

    def test_convert_failure_message_to_openai_message(self):
        message = FailureMessage(content="Error occurred", id="fail_123")

        result = convert_to_openai_message(message, {})

        assert len(result) == 1
        assert result[0].content == "Error occurred"
        assert result[0].id == "fail_123"

    def test_convert_failure_message_with_no_content(self):
        message = FailureMessage(content=None, id="fail_456")

        result = convert_to_openai_message(message, {})

        assert len(result) == 1
        assert result[0].content == "An unknown failure occurred."
        assert result[0].id == "fail_456"

    def test_convert_to_openai_messages_with_mixed_conversation(self):
        conversation = [
            HumanMessage(content="Hello", id="human_1"),
            AssistantMessage(
                content="Hi there",
                id="asst_1",
                tool_calls=[{"id": "tool_1", "name": "search", "args": {"query": "greeting"}}],
            ),
            HumanMessage(content="Follow up", id="human_2"),
            AssistantMessage(content="Response", id="asst_2", tool_calls=[]),
            FailureMessage(content="Error", id="fail_1"),
        ]
        tool_result_map = {
            "tool_1": AssistantToolCallMessage(content="Search done", id="result_1", tool_call_id="tool_1"),
        }

        result = convert_to_openai_messages(conversation, tool_result_map)  # type: ignore

        assert len(result) == 6
        assert result[0].content == "Hello"
        assert result[1].content == "Hi there"
        assert result[2].content == "Search done"
        assert result[3].content == "Follow up"
        assert result[4].content == "Response"
        assert result[5].content == "Error"

    def test_convert_to_openai_messages_handles_context_messages(self):
        conversation = [
            ContextMessage(content="System context"),
            HumanMessage(content="User question", id="human_1"),
            AssistantMessage(content="Answer", id="asst_1", tool_calls=[]),
        ]

        result = convert_to_openai_messages(conversation, {})  # type: ignore

        assert len(result) == 3
        assert result[0].content == "System context"
        assert result[1].content == "User question"
        assert result[2].content == "Answer"

    def test_convert_to_openai_messages_skips_unknown_message_types(self):
        conversation = [
            HumanMessage(content="Hello", id="human_1"),
            AssistantMessage(content="Response", id="asst_1", tool_calls=[]),
        ]

        result = convert_to_openai_messages(conversation, {})  # type: ignore

        assert len(result) == 2
