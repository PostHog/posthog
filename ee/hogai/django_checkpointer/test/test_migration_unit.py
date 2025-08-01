"""
Unit tests for checkpoint migration logic.

These tests focus on the migration logic without requiring database access.
"""

from ee.hogai.django_checkpoint.migrating_checkpointer import MigratingDjangoCheckpointer
from ee.hogai.utils.graph_states import AssistantGraphState, InsightsGraphState
from langgraph.checkpoint.base.id import uuid6


class TestMigrationUnit:
    """Unit tests for migration logic without database dependencies."""

    def setup_method(self):
        """Set up test fixtures."""
        self.checkpointer = MigratingDjangoCheckpointer()

    def test_get_target_state_type_for_root_namespace(self):
        """Test that root namespace (empty string) maps to AssistantGraphState."""
        target_type = self.checkpointer._get_target_state_type("")
        assert target_type == AssistantGraphState

    def test_get_target_state_type_for_insights_subgraph_namespace(self):
        """Test that only insights_subgraph namespace maps to InsightsGraphState."""
        # Only the exact insights_subgraph namespace should map to InsightsGraphState
        target_type = self.checkpointer._get_target_state_type("insights_subgraph")
        assert target_type == InsightsGraphState

    def test_get_target_state_type_for_unknown_namespace(self):
        """Test that unknown namespaces default to AssistantGraphState."""
        target_type = self.checkpointer._get_target_state_type("unknown_graph")
        assert target_type == AssistantGraphState

    def test_migrate_legacy_assistant_state_to_assistant_graph_state(self):
        """Test migration of legacy AssistantState to AssistantGraphState."""
        # Create legacy checkpoint data (simulating old AssistantState)
        # Use proper PostHog message format
        legacy_state_data = {
            "messages": [{"type": "human", "content": "Hello"}, {"type": "ai", "content": "Hi there!"}],
            "start_id": "msg-123",
            "root_tool_call_id": "tool-456",
            "root_tool_calls_count": 1,  # This indicates legacy format
            "graph_status": "resumed",
            # Legacy fields that should be preserved for parent graph
            "onboarding_question": "What can I help you with?",
            "search_insights_query": "user behavior trends",
            # Legacy fields that should be dropped (insights-specific)
            "plan": "This should be dropped",
            "intermediate_steps": None,  # Use None instead of invalid tuple format
            "rag_context": "This should be dropped",
            "query_generation_retry_count": 2,
        }

        checkpoint_data = {
            "v": 1,
            "id": str(uuid6()),
            "channel_values": {"__start__": legacy_state_data},
            "channel_versions": {"__start__": 1},
            "versions_seen": {},
            "pending_sends": [],
        }

        # Migrate for root namespace (AssistantGraphState)
        migrated_data = self.checkpointer._migrate_checkpoint_data(checkpoint_data, "")

        # Verify migration occurred
        migrated_state = migrated_data["channel_values"]["__start__"]

        # Verify migration occurred (should have migrated from legacy)
        # The migrated state will have all AssistantGraphState fields with proper defaults
        assert "messages" in migrated_state
        assert "start_id" in migrated_state
        assert "graph_status" in migrated_state

        # Key test: migration should have preserved compatible fields and added defaults
        assert len(migrated_state["messages"]) >= 2  # Original messages preserved
        assert migrated_state["start_id"] == "msg-123"
        assert migrated_state["graph_status"] == "resumed"

    def test_migrate_legacy_assistant_state_to_insights_graph_state(self):
        """Test migration of legacy AssistantState to InsightsGraphState."""
        # Create legacy checkpoint data with insights-specific fields
        legacy_state_data = {
            "messages": [
                {"type": "human", "content": "Show me trends"},
                {"type": "ai", "content": "Creating trends chart..."},
            ],
            "graph_status": "interrupted",
            "plan": "Create a trends query for page views",
            "intermediate_steps": None,  # Use None to avoid validation issues
            "rag_context": "Page views are tracked events...",
            "query_generation_retry_count": 1,
            "root_tool_insight_plan": "Generate trends insight",
            "root_tool_insight_type": "trends",  # This indicates legacy format
            # Parent-specific fields that should be dropped
            "start_id": "msg-789",
            "root_tool_call_id": "tool-abc",
            "onboarding_question": "This should be dropped",
            "search_insights_query": "This should be dropped",
        }

        checkpoint_data = {
            "v": 1,
            "id": str(uuid6()),
            "channel_values": {"insights_state": legacy_state_data},
            "channel_versions": {"insights_state": 1},
            "versions_seen": {},
            "pending_sends": [],
        }

        # Migrate for insights_subgraph namespace (the actual subgraph)
        migrated_data = self.checkpointer._migrate_checkpoint_data(checkpoint_data, "insights_subgraph")

        # Verify migration occurred
        migrated_state = migrated_data["channel_values"]["insights_state"]

        # Verify migration occurred (should have migrated from legacy)
        # The migrated state will have all InsightsGraphState fields with proper defaults
        assert "messages" in migrated_state
        assert "graph_status" in migrated_state
        assert "plan" in migrated_state

        # Key test: migration should have preserved insights-specific fields
        assert len(migrated_state["messages"]) >= 2  # Original messages preserved
        assert migrated_state["graph_status"] == "interrupted"
        assert migrated_state["plan"] == "Create a trends query for page views"
        assert migrated_state["rag_context"] == "Page views are tracked events..."
        assert migrated_state["query_generation_retry_count"] == 1

    def test_no_migration_needed_for_already_migrated_state(self):
        """Test that already-migrated states don't trigger errors."""
        # Create properly structured AssistantGraphState data (without legacy indicators)
        assistant_state_data = {
            "messages": [{"type": "human", "content": "Hello"}],
            "start_id": "msg-123",
            "graph_status": None,
            # Only fields that exist in AssistantGraphState, no legacy indicators
        }

        checkpoint_data = {
            "v": 1,
            "id": str(uuid6()),
            "channel_values": {"__start__": assistant_state_data},
            "channel_versions": {"__start__": 1},
            "versions_seen": {},
            "pending_sends": [],
        }

        # Migrate for root namespace
        migrated_data = self.checkpointer._migrate_checkpoint_data(checkpoint_data, "")

        # Migration should complete successfully even if state was already migrated
        # (The migration process might still add defaults, but should not fail)
        migrated_state = migrated_data["channel_values"]["__start__"]
        assert "messages" in migrated_state
        assert migrated_state["start_id"] == "msg-123"

    def test_empty_checkpoint_data_handling(self):
        """Test handling of empty or invalid checkpoint data."""
        # Empty checkpoint data
        empty_data = {}
        result = self.checkpointer._migrate_checkpoint_data(empty_data, "")
        assert result == empty_data

        # Checkpoint with no channel_values
        no_channels = {"v": 1, "id": str(uuid6())}
        result = self.checkpointer._migrate_checkpoint_data(no_channels, "")
        assert result == no_channels

        # Checkpoint with empty channel_values
        empty_channels = {"v": 1, "id": str(uuid6()), "channel_values": {}}
        result = self.checkpointer._migrate_checkpoint_data(empty_channels, "")
        assert result == empty_channels

    def test_migration_error_handling(self):
        """Test error handling when migration encounters invalid data."""
        # Create checkpoint with invalid state data
        invalid_checkpoint = {
            "v": 1,
            "id": str(uuid6()),
            "channel_values": {
                "__start__": "invalid_state_data"  # Should be dict, not string
            },
            "channel_versions": {"__start__": 1},
            "versions_seen": {},
            "pending_sends": [],
        }

        # Migration should handle this gracefully and return original data
        migrated_data = self.checkpointer._migrate_checkpoint_data(invalid_checkpoint, "")

        # Should return original data unchanged when migration fails
        assert migrated_data == invalid_checkpoint

    def test_migration_with_multiple_channels(self):
        """Test migration when checkpoint has multiple state channels."""
        # Create checkpoint with multiple channels, only one with state data
        checkpoint_with_multiple_channels = {
            "v": 1,
            "ts": "2024-07-31T20:14:19.804150+00:00",
            "id": str(uuid6()),
            "channel_values": {
                "branch:to:node1": None,
                "messages": ["Hello", "Hi there"],
                "__start__": {
                    "messages": [{"type": "human", "content": "Hello"}],
                    "start_id": "msg-1",
                    "graph_status": None,
                    "plan": "Should be dropped for root",
                },
                "other_channel": {"not": "state_data"},
            },
            "channel_versions": {"branch:to:node1": 1, "messages": 2, "__start__": 1, "other_channel": 1},
            "versions_seen": {},
            "pending_sends": [],
        }

        # Migrate for root namespace
        migrated_data = self.checkpointer._migrate_checkpoint_data(checkpoint_with_multiple_channels, "")

        # Should only migrate the state channel (__start__)
        migrated_channels = migrated_data["channel_values"]

        # State channel should be migrated
        assert "messages" in migrated_channels["__start__"]
        assert "plan" not in migrated_channels["__start__"]

        # Other channels should be unchanged
        assert migrated_channels["branch:to:node1"] is None
        assert migrated_channels["messages"] == ["Hello", "Hi there"]
        assert migrated_channels["other_channel"]["not"] == "state_data"

    def test_migration_preserves_message_structure(self):
        """Test that message structure is correctly preserved during migration."""
        # Create checkpoint with complex message structure
        complex_messages = [
            {"type": "human", "content": "Show me funnel analysis", "id": "human-msg-1"},
            {"type": "assistant", "content": "I'll create a funnel analysis for you.", "id": "assistant-msg-1"},
            {"type": "visualization", "content": "Funnel chart data...", "id": "viz-msg-1"},
        ]

        legacy_checkpoint = {
            "v": 1,
            "ts": "2024-07-31T20:14:19.804150+00:00",
            "id": str(uuid6()),
            "channel_values": {
                "__start__": {
                    "messages": complex_messages,
                    "start_id": "human-msg-1",
                    "graph_status": None,
                    "plan": "Should be dropped",
                }
            },
            "channel_versions": {"__start__": 1},
            "versions_seen": {},
            "pending_sends": [],
        }

        # Migrate for root namespace
        migrated_data = self.checkpointer._migrate_checkpoint_data(legacy_checkpoint, "")
        migrated_state = migrated_data["channel_values"]["__start__"]

        # Messages should be preserved exactly
        assert migrated_state["messages"] == complex_messages
        assert migrated_state["start_id"] == "human-msg-1"

    def test_insights_search_maps_to_assistant_graph_state(self):
        """Test that insights_search node maps to AssistantGraphState, not InsightsGraphState."""
        # insights_search is a node in the main AssistantGraph, not the InsightsGraph subgraph
        target_type = self.checkpointer._get_target_state_type("insights_search")
        assert target_type == AssistantGraphState

    def test_other_insights_related_namespaces_map_to_assistant_state(self):
        """Test that insights-related namespaces (except insights_subgraph) map to AssistantGraphState."""
        # These should all map to AssistantGraphState because they're not the actual subgraph
        assistant_namespaces = [
            "insights_search",
            "insights_processor",
            "some_insights_related_node",
            "insights_tool",
            "insights_context",
        ]

        for namespace in assistant_namespaces:
            target_type = self.checkpointer._get_target_state_type(namespace)
            assert target_type == AssistantGraphState, f"Failed for namespace: {namespace}"

    def test_migration_preserves_none_values(self):
        """Test that None values in state fields are preserved correctly."""
        legacy_state_data = {
            "messages": [{"type": "human", "content": "Hello"}],
            "start_id": None,  # None value should be preserved
            "graph_status": None,
            "root_tool_call_id": None,
            "plan": "Should be dropped",
        }

        checkpoint_data = {
            "v": 1,
            "id": str(uuid6()),
            "channel_values": {"__start__": legacy_state_data},
            "channel_versions": {"__start__": 1},
            "versions_seen": {},
            "pending_sends": [],
        }

        # Migrate for root namespace
        migrated_data = self.checkpointer._migrate_checkpoint_data(checkpoint_data, "")
        migrated_state = migrated_data["channel_values"]["__start__"]

        # None values should be preserved
        assert migrated_state["start_id"] is None
        assert migrated_state["graph_status"] is None
        assert migrated_state["root_tool_call_id"] is None

        # Non-compatible fields should still be dropped
        assert "plan" not in migrated_state

    def test_migration_with_memory_namespace(self):
        """Test migration behavior with memory namespace (future extension)."""
        # Memory namespace should currently default to AssistantGraphState
        target_type = self.checkpointer._get_target_state_type("memory")
        assert target_type == AssistantGraphState

        target_type = self.checkpointer._get_target_state_type("memory_collector")
        assert target_type == AssistantGraphState
