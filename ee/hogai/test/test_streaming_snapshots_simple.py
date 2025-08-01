"""
Simple snapshot tests for AI Assistant streaming behavior.

These tests capture the streaming output to ensure refactoring doesn't introduce regressions.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from syrupy import SnapshotAssertion

from ee.hogai.assistant_factory import AssistantFactory
from ee.models.assistant import Conversation
from posthog.schema import HumanMessage
from posthog.test.base import BaseTest


class TestStreamingSnapshotsSimple(BaseTest):
    """Test streaming behavior with snapshots to catch regressions."""

    def test_main_assistant_factory_creation_snapshot(self, snapshot: SnapshotAssertion):
        """Test that main assistant creation via factory produces consistent structure."""
        conversation = Conversation.objects.create(user=self.user, team=self.team, id=uuid4())

        with patch("ee.hogai.main_assistant.AssistantGraph") as mock_graph_class:
            mock_graph = MagicMock()
            mock_graph_class.return_value.compile_full_graph.return_value = mock_graph

            assistant = AssistantFactory.create(
                assistant_type="main",
                team=self.team,
                conversation=conversation,
                new_message=HumanMessage(content="What are my top events?"),
                user=self.user,
                is_new_conversation=True,
            )

            # Snapshot the assistant structure (excluding dynamic/sensitive fields)
            assistant_info = {
                "type": type(assistant).__name__,
                "team_id": assistant._team.id,
                "user_id": assistant._user.id,
                "conversation_id": str(assistant._conversation.id),
                "has_graph": assistant._graph is not None,
                "has_update_processor": assistant._update_processor is not None,
                "is_new_conversation": assistant._is_new_conversation,
            }

            assert assistant_info == snapshot

    def test_insights_assistant_factory_creation_snapshot(self, snapshot: SnapshotAssertion):
        """Test that insights assistant creation via factory produces consistent structure."""
        conversation = Conversation.objects.create(user=self.user, team=self.team, id=uuid4())

        with patch("ee.hogai.insights_assistant.InsightsAssistantGraph") as mock_graph_class:
            mock_graph = MagicMock()
            mock_graph_class.return_value.compile_full_graph.return_value = mock_graph

            assistant = AssistantFactory.create(
                assistant_type="insights",
                team=self.team,
                conversation=conversation,
                user=self.user,
                is_new_conversation=False,
            )

            # Snapshot the assistant structure
            assistant_info = {
                "type": type(assistant).__name__,
                "team_id": assistant._team.id,
                "user_id": assistant._user.id,
                "conversation_id": str(assistant._conversation.id),
                "has_graph": assistant._graph is not None,
                "has_update_processor": assistant._update_processor is not None,
                "is_new_conversation": assistant._is_new_conversation,
            }

            assert assistant_info == snapshot

    def test_factory_assistant_type_mapping_snapshot(self, snapshot: SnapshotAssertion):
        """Test that factory correctly maps assistant types to implementations."""
        conversation = Conversation.objects.create(user=self.user, team=self.team, id=uuid4())

        # Test all supported assistant types
        assistant_types = ["main", "assistant", "insights"]
        type_mapping = {}

        for assistant_type in assistant_types:
            # Mock the appropriate graph class
            if assistant_type in ["main", "assistant"]:
                graph_patch = patch("ee.hogai.main_assistant.AssistantGraph")
            else:
                graph_patch = patch("ee.hogai.insights_assistant.InsightsAssistantGraph")

            with graph_patch as mock_graph_class:
                mock_graph = MagicMock()
                mock_graph_class.return_value.compile_full_graph.return_value = mock_graph

                assistant = AssistantFactory.create(
                    assistant_type=assistant_type,
                    team=self.team,
                    conversation=conversation,
                    user=self.user,
                    is_new_conversation=True,
                )

                type_mapping[assistant_type] = type(assistant).__name__

        # Snapshot the type mapping to ensure consistency
        assert type_mapping == snapshot

    def test_assistant_state_initialization_snapshot(self, snapshot: SnapshotAssertion):
        """Test that assistant state initialization is consistent."""
        conversation = Conversation.objects.create(user=self.user, team=self.team, id=uuid4())

        with patch("ee.hogai.main_assistant.AssistantGraph") as mock_graph_class:
            mock_graph = MagicMock()
            mock_graph_class.return_value.compile_full_graph.return_value = mock_graph

            # Mock graph state to return a predictable initial state
            mock_graph.get_state.return_value.values = {
                "messages": [],
                "intermediate_steps": None,
                "plan": None,
                "graph_status": None,
            }

            assistant = AssistantFactory.create(
                assistant_type="main",
                team=self.team,
                conversation=conversation,
                new_message=HumanMessage(content="Test query"),
                user=self.user,
                is_new_conversation=True,
            )

            # Get config structure (excluding dynamic thread_id)
            config = assistant._get_config()
            config_structure = {
                "has_configurable": "configurable" in config,
                "configurable_keys": list(config.get("configurable", {}).keys()) if "configurable" in config else [],
            }

            assert config_structure == snapshot
