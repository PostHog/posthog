from posthog.test.base import BaseTest

from langchain_core.messages import AIMessage
from parameterized import parameterized

from posthog.schema import (
    AssistantMessage,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    HumanMessage,
    VisualizationMessage,
)

from ee.hogai.utils.helpers import (
    find_start_message,
    find_start_message_idx,
    normalize_ai_message,
    should_output_assistant_message,
)


class TestAssistantHelpers(BaseTest):
    def test_should_output_assistant_message(self):
        """
        Test that the should_output_assistant_message filter works correctly:
        - AssistantMessage with content should return True
        - Empty AssistantMessage should return False
        - AssistantToolCallMessage with UI payload should return True
        - AssistantToolCallMessage without UI payload should also return True (not filtered)
        """
        # Should return True: AssistantMessage with content
        message_with_content = AssistantMessage(content="This message has content", type="ai")
        self.assertTrue(should_output_assistant_message(message_with_content))

        # Should return False: Empty AssistantMessage
        empty_message = AssistantMessage(content="", type="ai")
        self.assertFalse(should_output_assistant_message(empty_message))

        # Should return True: AssistantToolCallMessage with UI payload
        tool_message_with_payload = AssistantToolCallMessage(
            content="Tool result", tool_call_id="123", type="tool", ui_payload={"some": "data"}
        )
        self.assertTrue(should_output_assistant_message(tool_message_with_payload))

        # Should return True: AssistantToolCallMessage without UI payload (not filtered by this function)
        tool_message_without_payload = AssistantToolCallMessage(
            content="Tool result", tool_call_id="456", type="tool", ui_payload=None
        )
        self.assertTrue(should_output_assistant_message(tool_message_without_payload))

    @parameterized.expand(
        [
            ("no_start_id", [], None, 0),
            ("empty_messages", [], "some-id", 0),
            ("start_id_not_found", [HumanMessage(content="test", id="other-id")], "target-id", 0),
            (
                "single_matching_message",
                [HumanMessage(content="test", id="target-id")],
                "target-id",
                0,
            ),
            (
                "matching_message_at_end",
                [
                    AssistantMessage(content="response", type="ai"),
                    HumanMessage(content="question", id="target-id"),
                ],
                "target-id",
                1,
            ),
            (
                "matching_message_in_middle",
                [
                    HumanMessage(content="first", id="first-id"),
                    HumanMessage(content="second", id="target-id"),
                    AssistantMessage(content="response", type="ai"),
                ],
                "target-id",
                1,
            ),
            (
                "multiple_human_messages_match_first_from_end",
                [
                    HumanMessage(content="first", id="other-id"),
                    HumanMessage(content="second", id="target-id"),
                    AssistantMessage(content="response", type="ai"),
                    HumanMessage(content="third", id="another-id"),
                ],
                "target-id",
                1,
            ),
            (
                "non_human_message_with_matching_id_ignored",
                [
                    AssistantMessage(content="response", type="ai", id="target-id"),
                    HumanMessage(content="question", id="other-id"),
                ],
                "target-id",
                0,
            ),
            (
                "mixed_messages_finds_correct_human_message",
                [
                    HumanMessage(content="first", id="first-id"),
                    AssistantMessage(content="response 1", type="ai"),
                    VisualizationMessage(answer=AssistantTrendsQuery(series=[])),
                    HumanMessage(content="second", id="target-id"),
                    AssistantMessage(content="response 2", type="ai"),
                ],
                "target-id",
                3,
            ),
        ]
    )
    def test_find_start_message_idx(self, _name, messages, start_id, expected_idx):
        result = find_start_message_idx(messages, start_id)
        self.assertEqual(result, expected_idx)

    @parameterized.expand(
        [
            ("empty_messages", [], None, None),
            (
                "returns_first_message_when_no_start_id",
                [
                    HumanMessage(content="first", id="first-id"),
                    AssistantMessage(content="response", type="ai"),
                ],
                None,
                HumanMessage(content="first", id="first-id"),
            ),
            (
                "returns_matching_message",
                [
                    HumanMessage(content="first", id="first-id"),
                    HumanMessage(content="second", id="target-id"),
                    AssistantMessage(content="response", type="ai"),
                ],
                "target-id",
                HumanMessage(content="second", id="target-id"),
            ),
            (
                "returns_first_when_id_not_found",
                [
                    HumanMessage(content="first", id="first-id"),
                    AssistantMessage(content="response", type="ai"),
                ],
                "nonexistent-id",
                HumanMessage(content="first", id="first-id"),
            ),
        ]
    )
    def test_find_start_message(self, _name, messages, start_id, expected_message):
        result = find_start_message(messages, start_id)
        self.assertEqual(result, expected_message)


class TestNormalizeAIMessage(BaseTest):
    def test_normalize_ai_message_with_string_content(self):
        """Test normalizing AIMessage with simple string content"""
        message = AIMessage(
            content="Hello world",
            tool_calls=[
                {"id": "call_1", "name": "test_tool", "args": {"param": "value"}},
                {"id": "call_2", "name": "another_tool", "args": {"x": 1, "y": 2}},
            ],
        )

        [result] = normalize_ai_message(message)

        self.assertIsInstance(result, AssistantMessage)
        self.assertEqual(result.content, "Hello world")
        self.assertEqual(result.type, "ai")
        self.assertIsNotNone(result.id)

        assert isinstance(result.tool_calls, list)
        self.assertEqual(len(result.tool_calls), 2)
        self.assertEqual(result.tool_calls[0].id, "call_1")
        self.assertEqual(result.tool_calls[0].name, "test_tool")
        self.assertEqual(result.tool_calls[0].args, {"param": "value"})
        self.assertEqual(result.tool_calls[1].id, "call_2")
        self.assertEqual(result.tool_calls[1].name, "another_tool")
        self.assertEqual(result.tool_calls[1].args, {"x": 1, "y": 2})

        self.assertIsNone(result.meta)

    def test_normalize_ai_message_with_no_tool_calls(self):
        """Test normalizing AIMessage without tool calls"""
        message = AIMessage(content="Simple message", tool_calls=[])

        [result] = normalize_ai_message(message)

        self.assertEqual(result.content, "Simple message")
        assert isinstance(result.tool_calls, list)
        self.assertEqual(len(result.tool_calls), 0)
        self.assertIsNone(result.meta)

    def test_normalize_ai_message_with_complex_content_text_only(self):
        """Test normalizing AIMessage with complex content containing only text blocks"""
        message = AIMessage(
            content=[
                "First text block",
                {"type": "text", "text": "Second text block"},
                "Third text block",
            ],
            tool_calls=[],
        )

        [result] = normalize_ai_message(message)

        expected_content = "First text blockSecond text blockThird text block"
        self.assertEqual(result.content, expected_content)
        self.assertIsNone(result.meta)

    def test_normalize_ai_message_with_thinking_content(self):
        """Test normalizing AIMessage with thinking blocks"""
        thinking_block = {"type": "thinking", "content": "Let me think about this..."}
        redacted_thinking_block = {"type": "redacted_thinking", "content": "Redacted thoughts"}

        message = AIMessage(
            content=[
                "Regular text",
                thinking_block,
                {"type": "text", "text": "More text"},
                redacted_thinking_block,
            ],
            tool_calls=[],
        )

        [result] = normalize_ai_message(message)

        self.assertEqual(result.content, "Regular textMore text")
        assert result.meta is not None
        assert result.meta.thinking is not None
        self.assertEqual(len(result.meta.thinking), 2)
        self.assertEqual(result.meta.thinking[0], thinking_block)
        self.assertEqual(result.meta.thinking[1], redacted_thinking_block)

    def test_normalize_ai_message_with_mixed_content(self):
        """Test normalizing AIMessage with mixed content types including thinking"""
        message = AIMessage(
            content=[
                "Start text",
                {"type": "thinking", "reasoning": "Complex reasoning here"},
                {"type": "text", "text": "Middle text"},
                {"type": "other", "data": "should be ignored"},
                "End text",
                {"type": "redacted_thinking", "content": "Secret thoughts"},
            ],
            tool_calls=[{"id": "tool_1", "name": "search", "args": {"query": "test"}}],
        )

        [result] = normalize_ai_message(message)

        self.assertEqual(result.content, "Start textMiddle textEnd text")
        assert isinstance(result.tool_calls, list)
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0].name, "search")

        assert result.meta is not None
        assert result.meta.thinking is not None
        self.assertEqual(len(result.meta.thinking), 2)
        self.assertEqual(result.meta.thinking[0]["type"], "thinking")
        self.assertEqual(result.meta.thinking[1]["type"], "redacted_thinking")

    def test_normalize_ai_message_empty_content_list(self):
        """Test normalizing AIMessage with empty content list"""
        message = AIMessage(content=[], tool_calls=[])

        [result] = normalize_ai_message(message)

        self.assertEqual(result.content, "")
        self.assertIsNone(result.meta)

    def test_normalize_ai_message_only_thinking(self):
        """Test normalizing AIMessage with only thinking blocks"""
        message = AIMessage(
            content=[
                {"type": "thinking", "content": "First thought"},
                {"type": "redacted_thinking", "content": "Second thought"},
            ],
            tool_calls=[],
        )

        [result] = normalize_ai_message(message)

        self.assertEqual(result.content, "")
        self.assertIsNotNone(result.meta)
        assert result.meta is not None
        assert result.meta.thinking is not None
        self.assertEqual(len(result.meta.thinking), 2)

        # OpenAI format
        message = AIMessage(
            content=[], tool_calls=[], additional_kwargs={"reasoning": {"summary": [{"text": "Some thinking"}]}}
        )

        [result] = normalize_ai_message(message)

        self.assertEqual(result.content, "")
        self.assertIsNotNone(result.meta)
        assert result.meta is not None
        assert result.meta.thinking is not None
        self.assertEqual(len(result.meta.thinking), 1)

    def test_normalize_ai_message_with_web_search_tool(self):
        """Test normalizing AIMessage with web_search tool use in content blocks"""
        message = AIMessage(
            content=[
                {"type": "text", "text": "Let me search for that information."},
                {
                    "type": "tool_use",
                    "id": "toolu_01A1B2C3D4E5F6G7H8I9J0K1",
                    "name": "web_search",
                    "input": {"query": "PostHog documentation"},
                },
                {"type": "text", "text": "Based on the search results..."},
            ],
            tool_calls=[],
        )

        [result] = normalize_ai_message(message)

        self.assertEqual(result.content, "Let me search for that information.Based on the search results...")
        assert isinstance(result.tool_calls, list)
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0].id, "toolu_01A1B2C3D4E5F6G7H8I9J0K1")
        self.assertEqual(result.tool_calls[0].name, "web_search")
        self.assertEqual(result.tool_calls[0].args, {"query": "PostHog documentation"})

    def test_normalize_ai_message_with_mixed_tool_calls_and_web_search(self):
        """Test normalizing AIMessage with both regular tool_calls and web_search in content"""
        message = AIMessage(
            content=[
                {"type": "text", "text": "I'll use multiple tools."},
                {
                    "type": "tool_use",
                    "id": "web_search_123",
                    "name": "web_search",
                    "input": {"query": "latest PostHog features"},
                },
            ],
            tool_calls=[{"id": "regular_tool_456", "name": "read_taxonomy", "args": {}}],
        )

        [result] = normalize_ai_message(message)

        self.assertEqual(result.content, "I'll use multiple tools.")
        assert isinstance(result.tool_calls, list)
        self.assertEqual(len(result.tool_calls), 2)
        # Regular tool call should come first (from tool_calls property)
        self.assertEqual(result.tool_calls[0].id, "regular_tool_456")
        self.assertEqual(result.tool_calls[0].name, "read_taxonomy")
        # Web search should be appended (from content blocks)
        self.assertEqual(result.tool_calls[1].id, "web_search_123")
        self.assertEqual(result.tool_calls[1].name, "web_search")


class TestExtractThinkingFromAIMessage(BaseTest):
    """Test extract_thinking_from_ai_message with various formats."""

    def test_extract_thinking_from_anthropic_format(self):
        """Test extracting thinking from Anthropic format."""
        from ee.hogai.utils.helpers import extract_thinking_from_ai_message

        message = AIMessage(
            content=[
                {"type": "thinking", "thinking": "Anthropic style reasoning"},
                {"type": "text", "text": "Response"},
            ]
        )

        thinking = extract_thinking_from_ai_message(message)

        self.assertIsNotNone(thinking)
        self.assertEqual(len(thinking), 1)
        self.assertEqual(thinking[0]["thinking"], "Anthropic style reasoning")

    def test_extract_thinking_from_openai_format(self):
        """Test extracting thinking from OpenAI o3/o4 format."""
        from ee.hogai.utils.helpers import extract_thinking_from_ai_message

        message = AIMessage(content=[], additional_kwargs={"reasoning": {"summary": [{"text": "OpenAI reasoning"}]}})

        thinking = extract_thinking_from_ai_message(message)

        self.assertIsNotNone(thinking)
        self.assertEqual(len(thinking), 1)

    def test_extract_thinking_returns_none_when_no_thinking(self):
        """Test that None is returned when message has no thinking."""
        from ee.hogai.utils.helpers import extract_thinking_from_ai_message

        message = AIMessage(content="Just regular text")

        thinking = extract_thinking_from_ai_message(message)

        self.assertEqual(thinking, [])

    def test_extract_thinking_with_redacted_thinking(self):
        """Test extracting both thinking and redacted_thinking."""
        from ee.hogai.utils.helpers import extract_thinking_from_ai_message

        message = AIMessage(
            content=[
                {"type": "thinking", "content": "Normal thought"},
                {"type": "redacted_thinking", "content": "Redacted"},
                {"type": "text", "text": "Response"},
            ]
        )

        thinking = extract_thinking_from_ai_message(message)

        self.assertIsNotNone(thinking)
        self.assertEqual(len(thinking), 2)

    def test_extract_thinking_preserves_block_structure(self):
        """Test that thinking blocks preserve their full structure."""
        from ee.hogai.utils.helpers import extract_thinking_from_ai_message

        thinking_block = {"type": "thinking", "thinking": "Main thought", "metadata": {"confidence": 0.95}}

        message = AIMessage(content=[thinking_block, {"type": "text", "text": "Response"}])

        thinking = extract_thinking_from_ai_message(message)

        self.assertIsNotNone(thinking)
        self.assertEqual(thinking[0], thinking_block)

    def test_extract_thinking_from_mixed_content(self):
        """Test extracting thinking from content with various block types."""
        from ee.hogai.utils.helpers import extract_thinking_from_ai_message

        message = AIMessage(
            content=[
                "String text",
                {"type": "text", "text": "Dict text"},
                {"type": "thinking", "content": "Thought 1"},
                {"type": "other", "data": "ignored"},
                {"type": "redacted_thinking", "content": "Thought 2"},
            ]
        )

        thinking = extract_thinking_from_ai_message(message)

        self.assertIsNotNone(thinking)
        self.assertEqual(len(thinking), 2)
        self.assertEqual(thinking[0]["content"], "Thought 1")
        self.assertEqual(thinking[1]["content"], "Thought 2")
