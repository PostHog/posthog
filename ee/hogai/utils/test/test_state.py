from ee.hogai.utils.types import add_and_merge_messages
from posthog.schema import AssistantMessage
from posthog.test.base import BaseTest


class TestState(BaseTest):
    def test_merge_messages_with_same_id(self):
        """Test that when messages with the same ID are merged, the message from the right list replaces the one in the left list."""
        # Create two messages with the same ID
        message_id = "test-id-123"
        left_message = AssistantMessage(id=message_id, content="Left message content")
        right_message = AssistantMessage(id=message_id, content="Right message content")

        # Merge the messages
        left = [left_message]
        right = [right_message]
        result = add_and_merge_messages(left, right)

        # Verify that the message from the right list replaces the one in the left list
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, message_id)
        self.assertEqual(result[0].content, "Right message content")

    def test_merge_messages_with_same_content_no_id(self):
        """Test that messages with the same content but no ID are not merged."""
        # Create two messages with the same content but no ID
        left_message = AssistantMessage(content="Same content")
        right_message = AssistantMessage(content="Same content")

        # Merge the messages
        left = [left_message]
        right = [right_message]
        result = add_and_merge_messages(left, right)

        # Verify that both messages are in the result with different IDs
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].content, "Same content")
        self.assertEqual(result[1].content, "Same content")
        self.assertIsNotNone(result[0].id)
        self.assertIsNotNone(result[1].id)
        self.assertNotEqual(result[0].id, result[1].id)
