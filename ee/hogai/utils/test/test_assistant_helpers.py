from posthog.test.base import BaseTest

from posthog.schema import AssistantMessage, AssistantToolCallMessage

from ee.hogai.utils.helpers import should_output_assistant_message


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
