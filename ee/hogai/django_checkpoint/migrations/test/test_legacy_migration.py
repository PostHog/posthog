import json
import pytest
from datetime import datetime, UTC
from unittest.mock import Mock, AsyncMock

from ee.hogai.django_checkpoint.migrations._0001_add_version_metadata import Migration0001
from ee.hogai.utils.types import AssistantState, GraphContext, GraphType, VersionMetadata
from ee.models.assistant import (
    Conversation,
    ConversationCheckpoint,
    ConversationCheckpointBlob,
)
from posthog.schema import HumanMessage


class TestMigration0001:
    """Test Migration0001 implementation."""

    def test_needs_migration_for_assistant_state_without_metadata(self):
        """Test that AssistantState without version_metadata needs migration."""
        state = AssistantState(messages=[], start_id="test-id", graph_status=None, plan=None)
        assert Migration0001.needs_migration(state) is True

    def test_needs_migration_for_dict_state_without_metadata(self):
        """Test that dict-based state without version_metadata needs migration."""
        state_dict = {"messages": [], "start_id": "test-id", "graph_status": None}
        assert Migration0001.needs_migration(state_dict) is True

    def test_does_not_need_migration_with_metadata(self):
        """Test that states with version_metadata don't need migration."""
        # Test AssistantState with metadata
        state = AssistantState(
            messages=[],
            start_id="test-id",
            version_metadata=VersionMetadata(
                schema_version=1,
                migrated_at=datetime.now(UTC).isoformat(),
                graph_type=GraphType.ASSISTANT,
                context=GraphContext.ROOT,
            ),
        )
        assert Migration0001.needs_migration(state) is False

        # Test dict with metadata
        state_dict = {
            "messages": [],
            "start_id": "test-id",
            "version_metadata": {
                "schema_version": 1,
                "migrated_at": datetime.now(UTC).isoformat(),
                "graph_type": "assistant",
                "context": "root",
            },
        }
        assert Migration0001.needs_migration(state_dict) is False

    def test_apply_to_assistant_state(self):
        """Test migration of AssistantState objects."""
        original_state = AssistantState(
            messages=[HumanMessage(content="test")], start_id="test-id", graph_status=None, plan=None
        )

        migrated_state = Migration0001.apply_to_state_object(original_state, GraphType.ASSISTANT, GraphContext.ROOT)

        assert isinstance(migrated_state, AssistantState)
        assert migrated_state.version_metadata is not None
        assert migrated_state.version_metadata.schema_version == 1
        assert migrated_state.version_metadata.graph_type == GraphType.ASSISTANT
        assert migrated_state.version_metadata.context == GraphContext.ROOT
        assert migrated_state.messages == original_state.messages

    def test_apply_to_dict_state(self):
        """Test migration of dict-based state data."""
        original_dict = {
            "messages": [{"id": "1", "type": "human", "content": "test"}],
            "start_id": "test-id",
            "graph_status": None,
        }

        migrated_dict = Migration0001.apply_to_state_object(original_dict, GraphType.ASSISTANT, GraphContext.ROOT)

        assert isinstance(migrated_dict, dict)
        assert "version_metadata" in migrated_dict
        assert migrated_dict["version_metadata"]["schema_version"] == 1
        assert migrated_dict["version_metadata"]["graph_type"] == "assistant"
        assert migrated_dict["version_metadata"]["context"] == "root"
        assert migrated_dict["messages"] == original_dict["messages"]

    def test_detect_graph_context_filter_options(self):
        """Test detection of filter options subgraph context."""
        checkpoint = Mock(spec=ConversationCheckpoint)
        checkpoint.checkpoint_ns = "root:path:root_tools:filter_options"
        checkpoint.thread = None

        graph_type, context = Migration0001.detect_graph_context(checkpoint)
        assert graph_type == GraphType.FILTER_OPTIONS
        assert context == GraphContext.SUBGRAPH

    def test_detect_graph_context_insights_subgraph(self):
        """Test detection of insights subgraph context."""
        checkpoint = Mock(spec=ConversationCheckpoint)
        checkpoint.checkpoint_ns = "root:path:insights_subgraph:nested"
        checkpoint.thread = None

        graph_type, context = Migration0001.detect_graph_context(checkpoint)
        assert graph_type == GraphType.INSIGHTS
        assert context == GraphContext.SUBGRAPH

    def test_detect_graph_context_insights_tool(self):
        """Test detection of insights tool context."""
        checkpoint = Mock(spec=ConversationCheckpoint)
        checkpoint.checkpoint_ns = ""
        thread = Mock(spec=Conversation)
        thread.type = "insights_tool"
        checkpoint.thread = thread

        graph_type, context = Migration0001.detect_graph_context(checkpoint)
        assert graph_type == GraphType.INSIGHTS
        assert context == GraphContext.ROOT

    def test_detect_graph_context_main_assistant(self):
        """Test detection of main assistant context."""
        checkpoint = Mock(spec=ConversationCheckpoint)
        checkpoint.checkpoint_ns = ""
        thread = Mock(spec=Conversation)
        thread.type = "assistant"
        checkpoint.thread = thread

        graph_type, context = Migration0001.detect_graph_context(checkpoint)
        assert graph_type == GraphType.ASSISTANT
        assert context == GraphContext.ROOT


@pytest.mark.asyncio
class TestMigrationApplication:
    """Test migration application to checkpoints and blobs."""

    async def test_apply_to_blob_skip_empty(self):
        """Test that empty blobs are skipped."""
        blob = Mock(spec=ConversationCheckpointBlob)
        blob.type = "empty"
        blob.blob = None

        result = await Migration0001.apply_to_blob_or_write(blob, Mock(), GraphType.ASSISTANT, GraphContext.ROOT)

        assert result is False

    async def test_apply_to_checkpoint_complete(self):
        """Test complete checkpoint migration including metadata update."""
        # Setup checkpoint with mocked relationships
        checkpoint = Mock(spec=ConversationCheckpoint)
        checkpoint.id = "checkpoint-1"
        checkpoint.checkpoint_ns = ""  # Main assistant namespace
        checkpoint.metadata = {}
        checkpoint.asave = AsyncMock()

        # Mock thread for context detection
        thread = Mock(spec=Conversation)
        thread.type = "assistant"
        checkpoint.thread = thread

        # Mock blobs
        blob1 = Mock(spec=ConversationCheckpointBlob)
        blob1.id = "blob-1"
        blob1.channel = "__start__"
        blob1.type = "msgpack"
        blob1.blob = b"data"
        blob1.asave = AsyncMock()

        # Mock async iteration for blobs
        async def mock_blob_iter():
            yield blob1

        checkpoint.blobs.all.return_value = mock_blob_iter()

        # Mock empty writes iteration
        async def mock_write_iter():
            return
            yield  # Make it an async generator

        checkpoint.writes.all.return_value = mock_write_iter()

        # Mock serde
        serde = Mock()
        legacy_state = {"messages": [], "start_id": "test"}
        serde.loads_typed.return_value = legacy_state
        serde.dumps_typed.return_value = ("msgpack", b"migrated")

        # Apply migration
        result = await Migration0001.apply_to_checkpoint(checkpoint, serde, GraphType.ASSISTANT, GraphContext.ROOT)

        assert result is True
        assert checkpoint.metadata["version_metadata"]["schema_version"] == 1
        checkpoint.asave.assert_called_once_with(update_fields=["metadata"])

    async def test_apply_to_blob_success(self):
        """Test successful migration of a checkpoint blob."""
        # Create a mock blob with legacy state data
        blob = Mock(spec=ConversationCheckpointBlob)
        blob.id = "test-blob-id"
        blob.channel = "__start__"
        blob.type = "msgpack"
        blob.blob = b"legacy_state_data"
        blob.asave = AsyncMock()

        # Mock serde to return/accept state objects
        serde = Mock()
        legacy_state = AssistantState(messages=[HumanMessage(content="test")], start_id="test-id")
        serde.loads_typed.return_value = legacy_state
        serde.dumps_typed.return_value = ("msgpack", b"migrated_state_data")

        # Apply migration
        result = await Migration0001.apply_to_blob_or_write(blob, serde, GraphType.ASSISTANT, GraphContext.ROOT)

        assert result is True
        assert blob.blob == b"migrated_state_data"
        blob.asave.assert_called_once_with(update_fields=["type", "blob"])


@pytest.mark.asyncio
class TestRealCheckpointFixtures:
    """Test with real checkpoint fixture data."""

    @pytest.fixture
    def fixture_data(self):
        """Load checkpoint fixtures."""
        with open("ee/hogai/django_checkpoint/test/checkpoint_fixtures.json") as f:
            return json.load(f)

    async def test_migrate_filter_options_checkpoint(self, fixture_data):
        """Test migration of real filter options checkpoint data."""
        checkpoint_data = fixture_data["checkpoints"][0]["checkpoints"][0]

        # Extract blob data
        blob_data = checkpoint_data["blobs"][0]["data"]["decoded_data"]

        # Check if it already has version_metadata (if so, remove it for testing)
        if "version_metadata" in blob_data:
            legacy_blob_data = blob_data.copy()
            del legacy_blob_data["version_metadata"]
        else:
            legacy_blob_data = blob_data

        # Verify it needs migration
        assert Migration0001.needs_migration(legacy_blob_data) is True

        # Apply migration
        migrated = Migration0001.apply_to_state_object(
            legacy_blob_data, GraphType.FILTER_OPTIONS, GraphContext.SUBGRAPH
        )

        # Verify migration applied
        assert "version_metadata" in migrated
        assert migrated["version_metadata"]["schema_version"] == 1
        assert migrated["version_metadata"]["graph_type"] == "filter_options"
        assert migrated["version_metadata"]["context"] == "subgraph"

        # Verify original data preserved
        assert migrated["start_id"] == legacy_blob_data["start_id"]
        assert migrated["messages"] == legacy_blob_data["messages"]

    async def test_migrate_insights_checkpoint(self, fixture_data):
        """Test migration of real insights checkpoint data."""
        checkpoint_data = fixture_data["checkpoints"][1]["checkpoints"][0]

        # Extract blob data
        blob_data = checkpoint_data["blobs"][0]["data"]["decoded_data"]

        # Apply migration
        migrated = Migration0001.apply_to_state_object(blob_data, GraphType.INSIGHTS, GraphContext.SUBGRAPH)

        # Verify migration
        assert "version_metadata" in migrated
        assert migrated["start_id"] == "c3a30824-901a-496a-aff7-f58fb483a597"
        assert len(migrated["messages"]) == 1

    async def test_migrate_main_assistant_checkpoint(self, fixture_data):
        """Test migration of real main assistant checkpoint data."""
        checkpoint_data = fixture_data["checkpoints"][2]["checkpoints"][0]

        # Extract blob data
        blob_data = checkpoint_data["blobs"][0]["data"]["decoded_data"]

        # Check if it already has version_metadata (if so, remove it for testing)
        if "version_metadata" in blob_data:
            legacy_blob_data = blob_data.copy()
            del legacy_blob_data["version_metadata"]
        else:
            legacy_blob_data = blob_data

        # Apply migration only if needed
        if Migration0001.needs_migration(legacy_blob_data):
            migrated = Migration0001.apply_to_state_object(legacy_blob_data, GraphType.ASSISTANT, GraphContext.ROOT)
        else:
            # Already migrated in fixture
            migrated = blob_data

        # Verify migration
        assert "version_metadata" in migrated
        assert migrated["version_metadata"]["graph_type"] == "assistant"
        assert migrated["version_metadata"]["context"] == "root"
        assert migrated["messages"][0]["content"] == "create a funnel"


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_migration_idempotency(self):
        """Test that migrations are idempotent."""
        # Create state with version metadata
        state = {
            "messages": [],
            "start_id": "test",
            "version_metadata": {
                "schema_version": 1,
                "migrated_at": "2024-01-01T00:00:00Z",
                "graph_type": "assistant",
                "context": "root",
            },
        }

        # Apply migration again
        result = Migration0001.apply_to_state_object(state, GraphType.ASSISTANT, GraphContext.ROOT)

        # Should return unchanged
        assert result == state

    def test_non_state_object_passthrough(self):
        """Test that non-state objects pass through unchanged."""
        non_state_data = {"some_other_field": "value", "not_a_state": True}

        assert Migration0001.needs_migration(non_state_data) is False

        result = Migration0001.apply_to_state_object(non_state_data, GraphType.ASSISTANT, GraphContext.ROOT)

        assert result == non_state_data

    @pytest.mark.asyncio
    async def test_migration_error_handling(self):
        """Test error handling during migration."""
        blob = Mock(spec=ConversationCheckpointBlob)
        blob.id = "error-blob"
        blob.type = "msgpack"
        blob.blob = b"data"

        # Mock serde to raise error
        serde = Mock()
        serde.loads_typed.side_effect = Exception("Deserialization error")

        # Should handle error gracefully
        result = await Migration0001.apply_to_blob_or_write(blob, serde, GraphType.ASSISTANT, GraphContext.ROOT)

        assert result is False
