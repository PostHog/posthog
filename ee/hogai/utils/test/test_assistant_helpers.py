from collections.abc import Sequence

import unittest
from posthog.test.base import BaseTest

from langchain_core.messages import AIMessage
from parameterized import parameterized

from posthog.schema import (
    ArtifactMessage,
    ArtifactSource,
    AssistantFunnelsEventsNode,
    AssistantFunnelsQuery,
    AssistantMessage,
    AssistantToolCallMessage,
    AssistantTrendsActionsNode,
    AssistantTrendsEventsNode,
    AssistantTrendsGroupNode,
    AssistantTrendsQuery,
    HumanMessage,
    NodeKind,
    VisualizationArtifactContent,
    VisualizationMessage,
)

from ee.hogai.utils.helpers import (
    assistant_query_to_dict,
    cast_assistant_query,
    convert_tool_messages_to_dict,
    find_start_message,
    find_start_message_idx,
    normalize_ai_message,
    should_output_assistant_message,
)
from ee.hogai.utils.types.base import AssistantMessageUnion


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
                    ArtifactMessage(
                        artifact_id="test-artifact-id",
                        source=ArtifactSource.ARTIFACT,
                        content=VisualizationArtifactContent(
                            query=AssistantTrendsQuery(series=[]), name="Test Artifact", description="Test plan"
                        ),
                    ),
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

        # OpenAI format - when content is a string (not list), extract_thinking_from_ai_message is used
        message = AIMessage(
            content="Some response",
            tool_calls=[],
            additional_kwargs={"reasoning": {"summary": [{"text": "Some thinking"}]}},
        )

        [result] = normalize_ai_message(message)

        self.assertEqual(result.content, "Some response")
        self.assertIsNotNone(result.meta)
        assert result.meta is not None
        assert result.meta.thinking is not None
        self.assertEqual(len(result.meta.thinking), 1)
        self.assertEqual(result.meta.thinking[0]["type"], "thinking")


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


class TestConvertToolMessagesToDict(BaseTest):
    """Test convert_tool_messages_to_dict function."""

    def test_convert_single_tool_message(self):
        """Test converting a single tool message to dictionary"""
        messages: Sequence[AssistantMessageUnion] = [
            AssistantToolCallMessage(content="Result 1", tool_call_id="tc1", type="tool"),
        ]

        result = convert_tool_messages_to_dict(messages)

        self.assertEqual(len(result), 1)
        self.assertIn("tc1", result)
        self.assertEqual(result["tc1"].content, "Result 1")

    def test_convert_multiple_tool_messages(self):
        """Test converting multiple tool messages"""
        messages: Sequence[AssistantMessageUnion] = [
            AssistantToolCallMessage(content="Result 1", tool_call_id="tc1", type="tool"),
            AssistantToolCallMessage(content="Result 2", tool_call_id="tc2", type="tool"),
            AssistantToolCallMessage(content="Result 3", tool_call_id="tc3", type="tool"),
        ]

        result = convert_tool_messages_to_dict(messages)

        self.assertEqual(len(result), 3)
        self.assertEqual(result["tc1"].content, "Result 1")
        self.assertEqual(result["tc2"].content, "Result 2")
        self.assertEqual(result["tc3"].content, "Result 3")

    def test_convert_ignores_non_tool_messages(self):
        """Test that non-tool messages are ignored"""
        messages: Sequence[AssistantMessageUnion] = [
            HumanMessage(content="Hello", id="h1"),
            AssistantMessage(content="Response", type="ai", id="a1"),
            AssistantToolCallMessage(content="Result 1", tool_call_id="tc1", type="tool"),
            VisualizationMessage(answer=AssistantTrendsQuery(series=[])),
        ]

        result = convert_tool_messages_to_dict(messages)

        self.assertEqual(len(result), 1)
        self.assertIn("tc1", result)

    def test_convert_empty_messages(self):
        """Test converting empty message list"""
        result = convert_tool_messages_to_dict([])
        self.assertEqual(len(result), 0)

    def test_convert_preserves_tool_call_metadata(self):
        """Test that tool message metadata is preserved"""
        messages: Sequence[AssistantMessageUnion] = [
            AssistantToolCallMessage(
                content="Result with UI", tool_call_id="tc1", type="tool", ui_payload={"data": "value"}
            ),
        ]

        result = convert_tool_messages_to_dict(messages)

        self.assertEqual(result["tc1"].ui_payload, {"data": "value"})


class TestNormalizeAIMessageWebSearch(BaseTest):
    """Test normalize_ai_message with web search and server tool use blocks."""

    def test_normalize_with_server_tool_use(self):
        """Test normalizing message with server_tool_use block"""
        message = AIMessage(
            content=[
                {"type": "text", "text": "Let me search for that."},
                {
                    "type": "server_tool_use",
                    "id": "search_1",
                    "name": "web_search",
                    "partial_json": '{"query": "test query"}',
                },
            ],
            tool_calls=[],
        )

        result = normalize_ai_message(message)

        # Server tool use should create two messages
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].content, "Let me search for that.")
        # First message has meta with empty thinking
        self.assertIsNone(result[0].meta)

        # Second message starts with server_tool_use
        self.assertEqual(result[1].content, "")
        self.assertIsNotNone(result[1].meta)
        assert result[1].meta is not None
        assert result[1].meta.thinking is not None
        self.assertEqual(len(result[1].meta.thinking), 1)
        self.assertEqual(result[1].meta.thinking[0]["type"], "server_tool_use")
        self.assertEqual(result[1].meta.thinking[0]["input"], {"query": "test query"})

    def test_normalize_with_web_search_result(self):
        """Test normalizing message with web_search_tool_result block"""
        message = AIMessage(
            content=[
                {
                    "type": "server_tool_use",
                    "id": "search_1",
                    "name": "web_search",
                    "partial_json": '{"query": "test"}',
                },
                {
                    "type": "web_search_tool_result",
                    "tool_use_id": "search_1",
                    "content": [{"type": "text", "text": "Search results here"}],
                },
                {"type": "text", "text": "Based on the search results..."},
            ],
            tool_calls=[],
        )

        result = normalize_ai_message(message)

        # Server tool use creates a new message
        self.assertEqual(len(result), 2)

        # Second message has both server_tool_use and web_search_tool_result in thinking
        assert result[1].meta is not None
        assert result[1].meta.thinking is not None
        self.assertEqual(len(result[1].meta.thinking), 2)
        self.assertEqual(result[1].meta.thinking[0]["type"], "server_tool_use")
        self.assertEqual(result[1].meta.thinking[1]["type"], "web_search_tool_result")
        self.assertEqual(result[1].content, "Based on the search results...")

    def test_normalize_with_citations(self):
        """Test normalizing message with citations in text blocks"""
        message = AIMessage(
            content=[
                {
                    "type": "text",
                    "text": "According to sources",
                    "citations": [
                        {"url": "https://example.com/article1"},
                        {"url": "https://docs.posthog.com/guide"},
                    ],
                }
            ],
            tool_calls=[],
        )

        [result] = normalize_ai_message(message)

        # Citations should be appended as markdown links
        self.assertIn("According to sources", result.content)
        self.assertIn("(example.com)", result.content)
        self.assertIn("https://example.com/article1", result.content)
        self.assertIn("(docs.posthog.com)", result.content)
        self.assertIn("https://docs.posthog.com/guide", result.content)

    def test_normalize_with_thinking_and_server_tool_use(self):
        """Test normalizing message with both thinking and server_tool_use blocks"""
        message = AIMessage(
            content=[
                {"type": "thinking", "thinking": "I need to search for this"},
                {"type": "text", "text": "Let me look that up."},
                {
                    "type": "server_tool_use",
                    "id": "search_1",
                    "name": "web_search",
                    "partial_json": '{"query": "info"}',
                },
                {"type": "text", "text": "Here's what I found."},
            ],
            tool_calls=[],
        )

        result = normalize_ai_message(message)

        # Should create two messages due to server_tool_use
        self.assertEqual(len(result), 2)

        # First message has thinking and text
        assert result[0].meta is not None
        assert result[0].meta.thinking is not None
        self.assertEqual(len(result[0].meta.thinking), 1)
        self.assertEqual(result[0].meta.thinking[0]["type"], "thinking")
        self.assertEqual(result[0].content, "Let me look that up.")

        # Second message has server_tool_use and subsequent text
        assert result[1].meta is not None
        assert result[1].meta.thinking is not None
        self.assertEqual(len(result[1].meta.thinking), 1)
        self.assertEqual(result[1].meta.thinking[0]["type"], "server_tool_use")
        self.assertEqual(result[1].content, "Here's what I found.")

    def test_normalize_with_invalid_partial_json(self):
        """Test normalizing message with invalid partial_json in server_tool_use"""
        message = AIMessage(
            content=[
                {
                    "type": "server_tool_use",
                    "id": "search_1",
                    "name": "web_search",
                    "partial_json": "{invalid json",  # Invalid JSON
                }
            ],
            tool_calls=[],
        )

        result = normalize_ai_message(message)

        # Should handle gracefully without crashing
        self.assertEqual(len(result), 2)
        assert result[1].meta is not None
        assert result[1].meta.thinking is not None
        self.assertEqual(len(result[1].meta.thinking), 1)
        # The input field should not be set due to JSON parse error
        self.assertNotIn("input", result[1].meta.thinking[0])

    def test_normalize_complex_web_search_flow(self):
        """Test normalizing a complete web search flow with multiple blocks"""
        message = AIMessage(
            content=[
                {"type": "thinking", "thinking": "User wants to know about X"},
                {"type": "text", "text": "Let me search for information about X."},
                {
                    "type": "server_tool_use",
                    "id": "search_1",
                    "name": "web_search",
                    "partial_json": '{"query": "information about X"}',
                },
                {
                    "type": "web_search_tool_result",
                    "tool_use_id": "search_1",
                    "content": [{"type": "text", "text": "Results..."}],
                },
                {"type": "thinking", "thinking": "Now I can answer"},
                {
                    "type": "text",
                    "text": "Based on my search",
                    "citations": [{"url": "https://source.com"}],
                },
            ],
            tool_calls=[],
        )

        result = normalize_ai_message(message)

        # Server tool use creates a split
        self.assertEqual(len(result), 2)

        # First message: thinking + text before server_tool_use
        assert result[0].meta is not None
        assert result[0].meta.thinking is not None
        self.assertEqual(len(result[0].meta.thinking), 1)
        self.assertEqual(result[0].meta.thinking[0]["type"], "thinking")
        self.assertEqual(result[0].content, "Let me search for information about X.")

        # Second message: server_tool_use + result + thinking + text with citations
        assert result[1].meta is not None
        assert result[1].meta.thinking is not None
        self.assertEqual(len(result[1].meta.thinking), 3)
        self.assertEqual(result[1].meta.thinking[0]["type"], "server_tool_use")
        self.assertEqual(result[1].meta.thinking[1]["type"], "web_search_tool_result")
        self.assertEqual(result[1].meta.thinking[2]["type"], "thinking")
        self.assertIn("Based on my search", result[1].content)
        self.assertIn("(source.com)", result[1].content)


class TestCastAssistantQuery(unittest.TestCase):
    def test_funnel_optional_step_survives_cast(self):
        query = AssistantFunnelsQuery(
            kind=NodeKind.FUNNELS_QUERY,
            series=[
                AssistantFunnelsEventsNode(event="signed up"),
                AssistantFunnelsEventsNode(event="profile filled", optionalInFunnel=True),
                AssistantFunnelsEventsNode(event="purchase"),
            ],
        )

        result = cast_assistant_query(query)

        assert result.kind == "FunnelsQuery"
        self.assertEqual(len(result.series), 3)
        self.assertFalse(bool(getattr(result.series[0], "optionalInFunnel", False)))
        self.assertTrue(bool(getattr(result.series[1], "optionalInFunnel", False)))
        self.assertFalse(bool(getattr(result.series[2], "optionalInFunnel", False)))

    @parameterized.expand(
        [
            ("$session_duration",),
            ("$is_bounce",),
            ("$pageview_count",),
            ("$screen_count",),
            ("$autocapture_count",),
            ("$num_uniq_urls",),
        ]
    )
    def test_session_math_property_type_is_filled_for_events_node(self, math_property: str) -> None:
        query = AssistantTrendsQuery(
            kind=NodeKind.TRENDS_QUERY,
            series=[
                AssistantTrendsEventsNode(event="$pageview", math="avg", math_property=math_property),
            ],
        )

        result = cast_assistant_query(query)

        assert result.kind == "TrendsQuery"
        assert getattr(result.series[0], "math_property_type", None) == "session_properties"

    def test_session_math_property_type_is_filled_for_actions_node(self) -> None:
        query = AssistantTrendsQuery(
            kind=NodeKind.TRENDS_QUERY,
            series=[
                AssistantTrendsActionsNode(id=1, name="signed up", math="avg", math_property="$session_duration"),
            ],
        )

        result = cast_assistant_query(query)

        assert result.kind == "TrendsQuery"
        assert getattr(result.series[0], "math_property_type", None) == "session_properties"

    def test_session_math_property_type_left_untouched_for_event_property(self) -> None:
        query = AssistantTrendsQuery(
            kind=NodeKind.TRENDS_QUERY,
            series=[
                AssistantTrendsEventsNode(event="$pageview", math="avg", math_property="refreshAge"),
            ],
        )

        result = cast_assistant_query(query)

        assert result.kind == "TrendsQuery"
        assert getattr(result.series[0], "math_property_type", None) is None

    def test_session_math_property_type_filled_inside_group_node(self) -> None:
        query = AssistantTrendsQuery(
            kind=NodeKind.TRENDS_QUERY,
            series=[
                AssistantTrendsGroupNode(
                    operator="OR",
                    math="avg",
                    math_property="$is_bounce",
                    nodes=[
                        AssistantTrendsEventsNode(event="$pageview", math="avg", math_property="$is_bounce"),
                        AssistantTrendsEventsNode(event="$pageleave", math="avg", math_property="$is_bounce"),
                    ],
                ),
            ],
        )

        result = cast_assistant_query(query)

        assert result.kind == "TrendsQuery"
        group = result.series[0]
        assert getattr(group, "math_property_type", None) == "session_properties"
        for inner in getattr(group, "nodes", []):
            assert getattr(inner, "math_property_type", None) == "session_properties"


class TestAssistantQueryToDict(unittest.TestCase):
    def test_session_math_property_filled_in_dump(self) -> None:
        query = AssistantTrendsQuery(
            kind=NodeKind.TRENDS_QUERY,
            series=[AssistantTrendsEventsNode(event="$pageview", math="avg", math_property="$is_bounce")],
        )

        dumped = assistant_query_to_dict(query)

        assert dumped["series"][0]["math_property_type"] == "session_properties"

    def test_event_property_left_untouched_in_dump(self) -> None:
        query = AssistantTrendsQuery(
            kind=NodeKind.TRENDS_QUERY,
            series=[AssistantTrendsEventsNode(event="$pageview", math="avg", math_property="refreshAge")],
        )

        dumped = assistant_query_to_dict(query)

        assert "math_property_type" not in dumped["series"][0]

    def test_no_op_for_non_trends_query(self) -> None:
        query = AssistantFunnelsQuery(
            kind=NodeKind.FUNNELS_QUERY,
            series=[AssistantFunnelsEventsNode(event="signed up"), AssistantFunnelsEventsNode(event="purchase")],
        )

        dumped = assistant_query_to_dict(query)

        assert dumped["kind"] == "FunnelsQuery"
        assert all("math_property_type" not in node for node in dumped["series"])


class TestSessionMathPropertiesAllowlist(unittest.TestCase):
    def test_runner_allowlist_is_imported(self) -> None:
        from posthog.hogql_queries.insights.trends.aggregation_operations import (
            ALLOWED_SESSION_MATH_PROPERTIES as runner_allowlist,
        )

        from ee.hogai.utils import helpers

        assert helpers.ALLOWED_SESSION_MATH_PROPERTIES is runner_allowlist
