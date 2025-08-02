"""
Snapshot tests for AI Assistant streaming behavior.

These tests capture the streaming output to ensure refactoring doesn't introduce regressions
in message ordering, formatting, or content.
"""

import asyncio
from unittest.mock import MagicMock, patch
from uuid import uuid4

from syrupy import SnapshotAssertion

from ee.hogai.assistant_factory import AssistantFactory
from ee.hogai.base_assistant import BaseAssistant
from ee.models.assistant import Conversation
from posthog.schema import HumanMessage
from posthog.test.base import BaseTest


class TestStreamingSnapshots(BaseTest):
    """Test streaming behavior with snapshots to catch regressions."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.conversation = Conversation.objects.create(user=self.user, team=self.team, id=uuid4())

    async def _collect_streaming_output(self, assistant: BaseAssistant) -> list[dict]:
        """Helper to collect all streaming chunks from an assistant."""
        chunks = []
        async for chunk in assistant.astream():
            chunks.append(
                {
                    "type": chunk[0],
                    "content": chunk[1].model_dump() if hasattr(chunk[1], "model_dump") else str(chunk[1]),
                }
            )
        return chunks

    async def test_main_assistant_streaming_simple_query(self, snapshot: SnapshotAssertion):
        """Test main assistant streaming output for a simple query."""

        # Mock the graph execution to return predictable output
        with patch("ee.hogai.main_assistant.AssistantGraph") as mock_graph_class:
            mock_graph = MagicMock()
            mock_graph_class.return_value.compile_full_graph.return_value = mock_graph

            # Mock streaming response
            async def mock_astream(*args, **kwargs):
                yield ("message", {"type": "ai", "content": "Hello! I'll help you with that.", "id": "msg_1"})
                yield ("thinking", {"type": "reasoning", "content": "Let me analyze your query...", "id": "think_1"})
                yield ("message", {"type": "ai", "content": " Here's what I found:", "id": "msg_1"})
                yield ("end", {"type": "end"})

            mock_graph.astream.return_value = mock_astream()

            # Create main assistant
            assistant = AssistantFactory.create(
                assistant_type="main",
                team=self.team,
                conversation=self.conversation,
                new_message=HumanMessage(content="What are my top events?"),
                user=self.user,
                is_new_conversation=True,
            )

            # Collect streaming output
            output = await self._collect_streaming_output(assistant)

            # Snapshot the output structure
            assert output == snapshot

    async def test_insights_assistant_streaming_generation(self, snapshot: SnapshotAssertion):
        """Test insights assistant streaming output for insight generation."""

        with patch("ee.hogai.insights_assistant.InsightsAssistantGraph") as mock_graph_class:
            mock_graph = MagicMock()
            mock_graph_class.return_value.compile_full_graph.return_value = mock_graph

            # Mock insight generation streaming
            async def mock_astream(*args, **kwargs):
                yield ("message", {"type": "ai", "content": "Generating your insight...", "id": "insight_1"})
                yield ("tool_call", {"type": "tool_call", "name": "generate_trends_insight", "id": "tool_1"})
                yield ("tool_result", {"type": "tool_result", "content": "Query executed successfully", "id": "tool_1"})
                yield ("message", {"type": "ai", "content": " Here's your trends analysis:", "id": "insight_1"})
                yield ("end", {"type": "end"})

            mock_graph.astream.return_value = mock_astream()

            # Create insights assistant
            assistant = AssistantFactory.create(
                assistant_type="insights",
                team=self.team,
                conversation=self.conversation,
                user=self.user,
                is_new_conversation=False,
            )

            # Collect streaming output
            output = await self._collect_streaming_output(assistant)

            # Snapshot the output structure
            assert output == snapshot

    async def test_streaming_error_handling(self, snapshot: SnapshotAssertion):
        """Test streaming behavior when errors occur."""

        with patch("ee.hogai.main_assistant.AssistantGraph") as mock_graph_class:
            mock_graph = MagicMock()
            mock_graph_class.return_value.compile_full_graph.return_value = mock_graph

            # Mock error during streaming
            async def mock_astream(*args, **kwargs):
                yield ("message", {"type": "ai", "content": "Starting analysis...", "id": "msg_1"})
                raise Exception("Test streaming error")

            mock_graph.astream.side_effect = mock_astream

            assistant = AssistantFactory.create(
                assistant_type="main",
                team=self.team,
                conversation=self.conversation,
                new_message=HumanMessage(content="Test query"),
                user=self.user,
                is_new_conversation=True,
            )

            # Collect output including error
            chunks = []
            try:
                async for chunk in assistant.astream():
                    chunks.append(
                        {
                            "type": chunk[0],
                            "content": chunk[1].model_dump() if hasattr(chunk[1], "model_dump") else str(chunk[1]),
                        }
                    )
            except Exception as e:
                chunks.append({"type": "error", "content": str(e)})

            # Snapshot error handling behavior
            assert chunks == snapshot

    async def test_streaming_message_ordering(self, snapshot: SnapshotAssertion):
        """Test that message ordering is consistent across assistant types."""

        # Test both assistant types to ensure consistent ordering
        outputs = {}
        assistant_types = ["main", "insights"]

        for assistant_type in assistant_types:
            graph_class_name = f"ee.hogai.{assistant_type}_assistant.{'AssistantGraph' if assistant_type == 'main' else 'InsightsAssistantGraph'}"

            with patch(graph_class_name) as mock_graph_class:
                mock_graph = MagicMock()
                mock_graph_class.return_value.compile_full_graph.return_value = mock_graph

                # Mock consistent streaming pattern
                async def mock_astream(*args, **kwargs):
                    yield ("start", {"type": "start", "timestamp": "2024-01-01T00:00:00Z"})
                    yield ("thinking", {"type": "reasoning", "content": "Analyzing...", "id": "think_1"})
                    yield ("message", {"type": "ai", "content": f"Response from assistant", "id": "msg_1"})
                    yield ("end", {"type": "end", "timestamp": "2024-01-01T00:00:01Z"})

                mock_graph.astream.return_value = mock_astream()

                assistant = AssistantFactory.create(
                    assistant_type=assistant_type,
                    team=self.team,
                    conversation=self.conversation,
                    new_message=HumanMessage(content="Test query") if assistant_type == "main" else None,
                    user=self.user,
                    is_new_conversation=True,
                )

                outputs[assistant_type] = await self._collect_streaming_output(assistant)

        # Snapshot both outputs to ensure consistent structure
        assert outputs == snapshot

    async def test_concurrent_streaming(self, snapshot: SnapshotAssertion):
        """Test streaming behavior under concurrent access."""

        async def create_and_stream(assistant_type: str, query: str):
            """Create assistant and collect streaming output."""
            graph_class_name = f"ee.hogai.{assistant_type}_assistant.{'AssistantGraph' if assistant_type == 'main' else 'InsightsAssistantGraph'}"

            with patch(graph_class_name) as mock_graph_class:
                mock_graph = MagicMock()
                mock_graph_class.return_value.compile_full_graph.return_value = mock_graph

                async def mock_astream(*args, **kwargs):
                    # Simulate some processing time
                    await asyncio.sleep(0.01)
                    yield ("message", {"type": "ai", "content": f"Processing: {query}", "id": f"msg_{assistant_type}"})
                    await asyncio.sleep(0.01)
                    yield ("end", {"type": "end"})

                mock_graph.astream.return_value = mock_astream()

                # Create new conversation for each concurrent request
                conversation = Conversation.objects.create(user=self.user, team=self.team, id=uuid4())

                assistant = AssistantFactory.create(
                    assistant_type=assistant_type,
                    team=self.team,
                    conversation=conversation,
                    new_message=HumanMessage(content=query) if assistant_type == "main" else None,
                    user=self.user,
                    is_new_conversation=True,
                )

                return await self._collect_streaming_output(assistant)

        # Run multiple concurrent streaming requests
        tasks = [
            create_and_stream("main", "Query 1"),
            create_and_stream("insights", "Query 2"),
            create_and_stream("main", "Query 3"),
        ]

        results = await asyncio.gather(*tasks)

        # Snapshot concurrent streaming results
        concurrent_output = {f"stream_{i}": output for i, output in enumerate(results)}
        assert concurrent_output == snapshot
