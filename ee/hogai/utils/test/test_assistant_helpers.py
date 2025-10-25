from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import (
    AssistantMessage,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    HumanMessage,
    VisualizationMessage,
)

from ee.hogai.utils.helpers import find_start_message, find_start_message_idx, should_output_assistant_message


class TestAssistantHelpers(BaseTest):
    def test_should_output_assistant_message(self):
        """
        Test that the should_output_assistant_message filter works correctly:
        - AssistantMessage with content should return True
        - Empty AssistantMessage should return False
        - AssistantToolCallMessage with UI payload should return True
        - AssistantToolCallMessage without UI payload should return False
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

        # Should return False: AssistantToolCallMessage without UI payload
        tool_message_without_payload = AssistantToolCallMessage(
            content="Tool result", tool_call_id="456", type="tool", ui_payload=None
        )
        self.assertFalse(should_output_assistant_message(tool_message_without_payload))

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
