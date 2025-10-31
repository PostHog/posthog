"""
Comprehensive tests for AssistantSSESerializer.

Tests the serialization of different event types for Server-Sent Events (SSE) streaming.
"""

from uuid import uuid4

from posthog.test.base import BaseTest

from posthog.schema import (
    AssistantEventType,
    AssistantMessage,
    AssistantToolCall,
    AssistantUpdateEvent,
    FailureMessage,
    MultiVisualizationMessage,
    NotebookUpdateMessage,
    ProsemirrorJSONContent,
    TrendsQuery,
    VisualizationItem,
    VisualizationMessage,
)

from ee.hogai.utils.sse import AssistantSSESerializer
from ee.models.assistant import Conversation


class TestAssistantSSESerializer(BaseTest):
    """Test the AssistantSSESerializer serialization logic."""

    def setUp(self):
        super().setUp()
        self.serializer = AssistantSSESerializer()

    def test_serializer_assistant_message(self):
        """Test SSE serialization of AssistantMessage."""
        message_id = str(uuid4())
        message = AssistantMessage(
            id=message_id,
            content="Test assistant response",
            tool_calls=[AssistantToolCall(id=str(uuid4()), name="test_tool", args={"param": "value"})],
        )

        result = self.serializer.dumps(message)

        # Verify SSE format
        self.assertIn(f"event: {AssistantEventType.MESSAGE}\n", result)
        self.assertIn("data: ", result)
        self.assertIn(f'"id":"{message_id}"', result)
        self.assertIn('"content":"Test assistant response"', result)
        self.assertIn('"tool_calls"', result)
        self.assertTrue(result.endswith("\n\n"))

    def test_serializer_assistant_update_event(self):
        """Test SSE serialization of AssistantUpdateEvent."""
        parent_id = str(uuid4())
        tool_call_id = str(uuid4())
        update = AssistantUpdateEvent(id=parent_id, content="Update content", tool_call_id=tool_call_id)

        result = self.serializer.dumps(update)

        # Verify SSE format
        self.assertIn(f"event: {AssistantEventType.UPDATE}\n", result)
        self.assertIn("data: ", result)
        self.assertIn(f'"id":"{parent_id}"', result)
        self.assertIn('"content":"Update content"', result)
        self.assertIn(f'"tool_call_id":"{tool_call_id}"', result)
        self.assertTrue(result.endswith("\n\n"))

    def test_serializer_visualization_message(self):
        """Test SSE serialization of VisualizationMessage."""
        query = TrendsQuery(series=[])
        viz_message = VisualizationMessage(query="Show me trends", answer=query, plan="I will show you trends")

        result = self.serializer.dumps(viz_message)

        # Verify SSE format
        self.assertIn(f"event: {AssistantEventType.MESSAGE}\n", result)
        self.assertIn("data: ", result)
        self.assertIn('"query":"Show me trends"', result)
        self.assertIn('"plan":"I will show you trends"', result)
        self.assertIn('"type":"ai/viz"', result)
        self.assertTrue(result.endswith("\n\n"))

    def test_serializer_multi_visualization_message(self):
        """Test SSE serialization of MultiVisualizationMessage."""
        query = TrendsQuery(series=[])
        viz_item = VisualizationItem(query="Show me trends", answer=query, plan="I will show you trends")
        multi_viz_message = MultiVisualizationMessage(visualizations=[viz_item])

        result = self.serializer.dumps(multi_viz_message)

        # Verify SSE format
        self.assertIn(f"event: {AssistantEventType.MESSAGE}\n", result)
        self.assertIn("data: ", result)
        self.assertIn('"type":"ai/multi_viz"', result)
        self.assertIn('"visualizations"', result)
        self.assertTrue(result.endswith("\n\n"))

    def test_serializer_failure_message(self):
        """Test SSE serialization of FailureMessage."""
        failure_message = FailureMessage(id=str(uuid4()), content="Something went wrong")

        result = self.serializer.dumps(failure_message)

        # Verify SSE format
        self.assertIn(f"event: {AssistantEventType.MESSAGE}\n", result)
        self.assertIn("data: ", result)
        self.assertIn('"content":"Something went wrong"', result)
        self.assertIn('"type":"ai/failure"', result)
        self.assertTrue(result.endswith("\n\n"))

    def test_serializer_notebook_update_message(self):
        """Test SSE serialization of NotebookUpdateMessage."""
        content = ProsemirrorJSONContent(type="doc", content=[])
        notebook_message = NotebookUpdateMessage(notebook_id="nb123", content=content)

        result = self.serializer.dumps(notebook_message)

        # Verify SSE format
        self.assertIn(f"event: {AssistantEventType.MESSAGE}\n", result)
        self.assertIn("data: ", result)
        self.assertIn('"notebook_id":"nb123"', result)
        self.assertIn('"type":"ai/notebook"', result)
        self.assertTrue(result.endswith("\n\n"))

    def test_serializer_conversation(self):
        """Test SSE serialization of Conversation object."""
        conversation = Conversation.objects.create(
            team=self.team,
            user=self.user,
        )

        result = self.serializer.dumps(conversation)

        # Verify SSE format
        self.assertIn(f"event: {AssistantEventType.CONVERSATION}\n", result)
        self.assertIn("data: ", result)
        # Conversation serialization uses Django's JSON encoder which adds spaces
        self.assertIn(f'"id": "{conversation.id}"', result)
        self.assertIn('"status"', result)
        self.assertTrue(result.endswith("\n\n"))

    def test_serializer_excludes_none_values(self):
        """Test that None values are excluded from serialization."""
        message = AssistantMessage(
            content="Test",
            # id is None by default
        )

        result = self.serializer.dumps(message)

        # Verify that 'id' field is not in the output since it's None
        self.assertNotIn('"id":', result)
        self.assertIn('"content":"Test"', result)

    def test_serializer_preserves_sse_format(self):
        """Test that SSE format is correctly structured with event and data lines."""
        message = AssistantMessage(content="Test")

        result = self.serializer.dumps(message)

        # Split into lines to verify structure
        lines = result.split("\n")
        self.assertEqual(lines[0], f"event: {AssistantEventType.MESSAGE}")
        self.assertTrue(lines[1].startswith("data: "))
        self.assertEqual(lines[2], "")  # Empty line at the end
        self.assertEqual(lines[3], "")  # Double newline
