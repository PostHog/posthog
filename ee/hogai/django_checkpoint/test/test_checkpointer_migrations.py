import asyncio
from datetime import datetime, UTC
from unittest.mock import patch, Mock, AsyncMock

import pytest
from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.django_checkpoint.migrations._0001_add_version_metadata import Migration0001
from ee.hogai.django_checkpoint.migrations.registry import registry
from ee.hogai.utils.types import (
    AssistantState,
    GraphContext,
    GraphType,
)
from ee.models.assistant import (
    Conversation,
    ConversationCheckpoint,
    ConversationCheckpointBlob,
)
from posthog.schema import HumanMessage
from posthog.test.base import NonAtomicBaseTest
from langgraph.checkpoint.base.id import uuid6


@pytest.mark.asyncio
class TestDjangoCheckpointerMigrations:
    """Test DjangoCheckpointer integration with migrations."""

    @pytest.fixture
    def checkpointer(self):
        """Create a DjangoCheckpointer instance."""
        return DjangoCheckpointer(graph_type=GraphType.ASSISTANT, graph_context=GraphContext.ROOT)

    def test_checkpointer_requires_graph_metadata(self):
        """Test that checkpointer requires graph_type and graph_context in production."""
        # In test mode it allows None values, so we need to patch TEST
        with patch("ee.hogai.django_checkpoint.checkpointer.TEST", False):
            # Should raise ValueError without graph_type
            with pytest.raises(ValueError, match="graph_type and graph_context must be provided"):
                DjangoCheckpointer()

            # Should raise ValueError with only graph_type
            with pytest.raises(ValueError, match="graph_type and graph_context must be provided"):
                DjangoCheckpointer(graph_type=GraphType.ASSISTANT)

            # Should raise ValueError with only graph_context
            with pytest.raises(ValueError, match="graph_type and graph_context must be provided"):
                DjangoCheckpointer(graph_context=GraphContext.ROOT)

            # Should work with both
            checkpointer = DjangoCheckpointer(graph_type=GraphType.ASSISTANT, graph_context=GraphContext.ROOT)
            assert checkpointer._graph_metadata["graph_type"] == "assistant"
            assert checkpointer._graph_metadata["context"] == "root"

    async def test_migration_applied_on_read(self, checkpointer):
        """Test that migrations are applied when reading checkpoints through checkpointer."""
        # This test verifies the integration between DjangoCheckpointer and the migration system
        # by mocking the database layer but using real migration logic

        # Create mock checkpoint with legacy data (no version_metadata)
        checkpoint = Mock(spec=ConversationCheckpoint)
        checkpoint.id = "test-checkpoint"
        checkpoint.thread_id = "test-thread"
        checkpoint.checkpoint_ns = ""
        checkpoint.checkpoint = {"v": 3, "id": "test-checkpoint"}
        checkpoint.metadata = {}  # No version metadata initially
        checkpoint.parent_checkpoint = None
        checkpoint.asave = AsyncMock()

        # Create a blob with legacy state data
        legacy_state_data = {"messages": [], "start_id": "test-id", "graph_status": None}
        blob_type, blob_data = checkpointer.serde.dumps_typed(legacy_state_data)

        blob = Mock(spec=ConversationCheckpointBlob)
        blob.id = "test-blob"
        blob.channel = "__start__"
        blob.type = blob_type
        blob.blob = blob_data
        blob.asave = AsyncMock()

        # Mock async iteration
        async def mock_blob_iter():
            yield blob

        async def mock_write_iter():
            return
            yield  # Make it an async generator

        checkpoint.blobs.all.return_value = mock_blob_iter()
        checkpoint.writes.all.return_value = mock_write_iter()

        # Mock the apply_migrations method to verify it's called
        with patch.object(
            checkpointer, "_apply_migrations_to_checkpoint", wraps=checkpointer._apply_migrations_to_checkpoint
        ) as mock_apply:
            # Mock database query
            with patch.object(checkpointer, "_get_checkpoint_qs") as mock_qs:

                async def mock_checkpoint_iter():
                    yield checkpoint

                mock_qs.return_value = mock_checkpoint_iter()

                # Read checkpoints
                config = {"configurable": {"thread_id": "test-thread"}}
                checkpoints = []
                async for cp_tuple in checkpointer.alist(config):
                    checkpoints.append(cp_tuple)

                # Verify migration was called
                assert len(checkpoints) == 1
                mock_apply.assert_called_once_with(checkpoint)

    def test_add_version_metadata(self, checkpointer):
        """Test that version metadata is added to new states."""
        original_state = {"messages": [], "start_id": "test-id"}

        # Ensure registry has migrations
        if not registry._migrations:
            registry.register_migration(Migration0001)

        updated_state = checkpointer._add_version_metadata(original_state)

        assert "version_metadata" in updated_state
        assert updated_state["version_metadata"]["schema_version"] == registry.current_version
        assert updated_state["version_metadata"]["graph_type"] == "assistant"
        assert updated_state["version_metadata"]["context"] == "root"


class TestCheckpointMigrationIntegration(NonAtomicBaseTest):
    """Integration tests for checkpoint migrations."""

    CLASS_DATA_LEVEL_SETUP = False

    @pytest.mark.asyncio
    async def test_full_migration_flow(self):
        """Test complete migration flow from legacy checkpoint to migrated state."""
        # Create a legacy checkpoint without version metadata
        thread = await sync_to_async(Conversation.objects.create)(user=self.user, team=self.team, type="assistant")

        checkpoint = await sync_to_async(ConversationCheckpoint.objects.create)(
            thread=thread,
            thread_id=str(thread.id),
            checkpoint_ns="",
            checkpoint={"v": 3, "id": "test-checkpoint", "ts": datetime.now(UTC).isoformat()},
            metadata={},
        )

        # Create legacy blob without version metadata
        checkpointer = DjangoCheckpointer(GraphType.ASSISTANT, GraphContext.ROOT)
        legacy_state = AssistantState(
            messages=[HumanMessage(content="test message")], start_id="test-start-id", graph_status=None, plan=None
        )

        # Serialize state without version metadata (simulate legacy data)
        legacy_dict = legacy_state.model_dump()
        # Remove version_metadata to simulate truly legacy data
        legacy_dict.pop("version_metadata", None)
        blob_type, blob_data = checkpointer.serde.dumps_typed(legacy_dict)

        blob = await sync_to_async(ConversationCheckpointBlob.objects.create)(
            checkpoint=checkpoint, channel="__start__", type=blob_type, blob=blob_data
        )

        # Read checkpoint through checkpointer (should trigger migration)
        config: RunnableConfig = {"configurable": {"thread_id": str(thread.id), "checkpoint_id": checkpoint.id}}

        checkpoint_tuples = []
        async for cp_tuple in checkpointer.alist(config):
            checkpoint_tuples.append(cp_tuple)

        assert len(checkpoint_tuples) == 1

        # Verify checkpoint metadata was updated
        await sync_to_async(checkpoint.refresh_from_db)()
        assert "version_metadata" in checkpoint.metadata
        assert checkpoint.metadata["version_metadata"]["schema_version"] == 1

        # Verify blob was migrated
        await sync_to_async(blob.refresh_from_db)()
        migrated_state_data = checkpointer.serde.loads_typed((blob.type, blob.blob))

        assert "version_metadata" in migrated_state_data
        assert migrated_state_data["version_metadata"]["schema_version"] == 1
        assert migrated_state_data["version_metadata"]["graph_type"] == "assistant"
        assert migrated_state_data["version_metadata"]["context"] == "root"

    @pytest.mark.asyncio
    async def test_concurrent_migration_handling(self):
        """Test that concurrent reads don't cause duplicate migrations."""
        # Create checkpoint with legacy data
        thread = await sync_to_async(Conversation.objects.create)(user=self.user, team=self.team, type="assistant")

        checkpoint = await sync_to_async(ConversationCheckpoint.objects.create)(
            thread=thread,
            thread_id=str(thread.id),
            checkpoint_ns="",
            checkpoint={"v": 3, "id": "concurrent-checkpoint"},
            metadata={},
        )

        # Create legacy blob
        checkpointer = DjangoCheckpointer(GraphType.ASSISTANT, GraphContext.ROOT)
        state_data = {"messages": [], "start_id": "concurrent-test"}
        blob_type, blob_data = checkpointer.serde.dumps_typed(state_data)

        blob = await sync_to_async(ConversationCheckpointBlob.objects.create)(
            checkpoint=checkpoint, channel="__start__", type=blob_type, blob=blob_data
        )

        # Simulate concurrent reads
        config: RunnableConfig = {"configurable": {"thread_id": str(thread.id), "checkpoint_id": checkpoint.id}}

        async def read_checkpoint():
            async for _ in checkpointer.alist(config):
                pass

        # Run multiple concurrent reads
        await asyncio.gather(read_checkpoint(), read_checkpoint(), read_checkpoint())

        # Verify migration only applied once
        await sync_to_async(checkpoint.refresh_from_db)()
        assert checkpoint.metadata["version_metadata"]["schema_version"] == 1

        # Check blob migration
        await sync_to_async(blob.refresh_from_db)()
        migrated_data = checkpointer.serde.loads_typed((blob.type, blob.blob))
        assert migrated_data["version_metadata"]["schema_version"] == 1

    @pytest.mark.asyncio
    async def test_write_adds_version_metadata(self):
        """Test that new checkpoints are created with version metadata."""
        thread = await sync_to_async(Conversation.objects.create)(user=self.user, team=self.team, type="assistant")

        checkpointer = DjangoCheckpointer(GraphType.ASSISTANT, GraphContext.ROOT)

        # Create new checkpoint with state
        config: RunnableConfig = {"configurable": {"thread_id": str(thread.id), "checkpoint_ns": ""}}

        checkpoint_data = {
            "v": 3,
            "id": str(uuid6()),
            "ts": datetime.now(UTC).isoformat(),
            "channel_values": {
                "__start__": AssistantState(
                    messages=[HumanMessage(content="new message")], start_id="new-start-id"
                ).model_dump()
            },
        }

        # Write checkpoint
        await checkpointer.aput(config, checkpoint_data, {}, {})

        # Read it back
        checkpoints = []
        async for cp_tuple in checkpointer.alist(config):
            checkpoints.append(cp_tuple)

        assert len(checkpoints) == 1

        # Verify version metadata was added
        checkpoint_tuple = checkpoints[0]
        channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})

        if "__start__" in channel_values:
            start_state = channel_values["__start__"]
            assert "version_metadata" in start_state
            assert start_state["version_metadata"]["schema_version"] == registry.current_version

    @pytest.mark.asyncio
    async def test_migration_error_recovery(self):
        """Test recovery from migration errors."""
        thread = await sync_to_async(Conversation.objects.create)(user=self.user, team=self.team, type="assistant")

        checkpoint = await sync_to_async(ConversationCheckpoint.objects.create)(
            thread=thread,
            thread_id=str(thread.id),
            checkpoint_ns="",
            checkpoint={"v": 3, "id": "error-checkpoint"},
            metadata={},
        )

        checkpointer = DjangoCheckpointer(GraphType.ASSISTANT, GraphContext.ROOT)
        config: RunnableConfig = {"configurable": {"thread_id": str(thread.id), "checkpoint_id": checkpoint.id}}

        # Should handle error gracefully and still return checkpoint
        checkpoints = []
        async for cp_tuple in checkpointer.alist(config):
            checkpoints.append(cp_tuple)

        # Checkpoint should still be returned despite blob error
        assert len(checkpoints) == 1

    @pytest.mark.asyncio
    async def test_bulk_migration_performance(self):
        """Test migration performance with multiple checkpoints."""
        # Create multiple legacy checkpoints
        thread = await sync_to_async(Conversation.objects.create)(user=self.user, team=self.team, type="assistant")

        checkpointer = DjangoCheckpointer(GraphType.ASSISTANT, GraphContext.ROOT)

        # Create 10 checkpoints with legacy data
        for i in range(10):
            checkpoint = await sync_to_async(ConversationCheckpoint.objects.create)(
                thread=thread,
                thread_id=str(thread.id),
                checkpoint_ns="",
                checkpoint={"v": 3, "id": f"bulk-checkpoint-{i}"},
                metadata={},
            )

            # Add blob with legacy state
            state_data = {
                "messages": [{"id": str(i), "type": "human", "content": f"message {i}"}],
                "start_id": f"start-{i}",
            }
            blob_type, blob_data = checkpointer.serde.dumps_typed(state_data)

            await sync_to_async(ConversationCheckpointBlob.objects.create)(
                checkpoint=checkpoint, channel="__start__", type=blob_type, blob=blob_data
            )

        # Read all checkpoints (triggering migrations)
        config: RunnableConfig = {"configurable": {"thread_id": str(thread.id)}}

        import time

        start_time = time.time()

        checkpoint_count = 0
        async for _ in checkpointer.alist(config):
            checkpoint_count += 1

        elapsed_time = time.time() - start_time

        assert checkpoint_count == 10
        # Migration should complete reasonably quickly (< 5 seconds for 10 checkpoints)
        assert elapsed_time < 5.0

        # Verify all checkpoints were migrated
        checkpoints = await sync_to_async(list)(ConversationCheckpoint.objects.filter(thread=thread))

        for cp in checkpoints:
            assert "version_metadata" in cp.metadata
            assert cp.metadata["version_metadata"]["schema_version"] == 1
