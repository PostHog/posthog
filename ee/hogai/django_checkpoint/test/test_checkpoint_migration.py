import json
import pytest
import uuid
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from django.test import TransactionTestCase
from langchain_core.runnables import RunnableConfig
from ee.hogai.django_checkpoint.migrations.migration_registry import migration_registry
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.django_checkpoint.context import CheckpointContext
from ee.hogai.utils.types import GraphContext, GraphType
from ee.models.assistant import Conversation, ConversationCheckpoint, ConversationCheckpointBlob
from posthog.schema import HumanMessage
from posthog.test.base import APIBaseTest


class TestCheckpointLazyMigration(APIBaseTest, TransactionTestCase):
    def setUp(self):
        super().setUp()

        # Use the already created test data from APIBaseTest
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)

        # Create checkpointer
        self.context = CheckpointContext(
            graph_type=GraphType.ASSISTANT,
            graph_context=GraphContext.ROOT,
            thread_id=str(self.conversation.id),
            thread_type=self.conversation.type,
        )
        self.checkpointer = DjangoCheckpointer(context=self.context)

    async def test_legacy_checkpoint_is_migrated_and_saved(self):
        """Test that when we read a legacy checkpoint, it gets migrated and saved back."""

        # Create a legacy checkpoint (msgpack format)
        checkpoint_id = str(uuid.uuid4())
        thread_id = str(self.conversation.id)

        # Create the checkpoint record
        checkpoint = await ConversationCheckpoint.objects.acreate(
            id=checkpoint_id,
            thread_id=thread_id,
            thread=self.conversation,
            checkpoint_ns="",
            checkpoint={"ts": checkpoint_id, "channel_versions": {"messages": "1"}},
            metadata={},
        )

        # Create a legacy blob with msgpack type
        # This simulates old data that needs migration
        legacy_message = HumanMessage(content="Hello from legacy", id=str(uuid.uuid4()))

        # Use the legacy serializer to create msgpack data
        legacy_serde = JsonPlusSerializer()
        type_str, blob = legacy_serde.dumps_typed([legacy_message])

        blob_record = await ConversationCheckpointBlob.objects.acreate(
            checkpoint=checkpoint,
            thread_id=thread_id,
            channel="messages",
            version="1",
            type=type_str,  # This will be "msgpack"
            blob=blob,
        )

        # Read the checkpoint - this should trigger migration
        config: RunnableConfig = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
                "checkpoint_ns": "",
            }
        }

        # Read the checkpoint - this should trigger migration
        checkpoint_tuple = await self.checkpointer.aget_tuple(config)

        # Verify we got the data
        assert checkpoint_tuple is not None
        messages = checkpoint_tuple.checkpoint["channel_values"]["messages"]
        assert len(messages) == 1
        assert messages[0].content == "Hello from legacy"

        # Reload the blob to verify it was updated
        await blob_record.arefresh_from_db()

        # The type should now be "json" instead of "msgpack"
        assert blob_record.type == "json", f"Expected type to be 'json', got {blob_record.type}"

        # Verify the data can still be loaded correctly
        checkpoint_tuple2 = await self.checkpointer.aget_tuple(config)
        assert checkpoint_tuple2 is not None
        messages2 = checkpoint_tuple2.checkpoint["channel_values"]["messages"]
        assert len(messages2) == 1
        assert (
            messages2[0].content == "Hello from legacy"
        )  # (This implicitly tests that migration doesn't happen again)

    async def test_versioned_checkpoint_migration(self):
        """Test that versioned checkpoints with old versions get migrated."""

        checkpoint_id = str(uuid.uuid4())
        thread_id = str(self.conversation.id)

        # Create a checkpoint with version 0 (will need migration if current version > 0)
        checkpoint = await ConversationCheckpoint.objects.acreate(
            id=checkpoint_id,
            thread_id=thread_id,
            thread=self.conversation,
            checkpoint_ns="",
            checkpoint={"ts": checkpoint_id, "channel_versions": {"test": "1"}},
            metadata={},
        )

        # Create versioned JSON data with old version
        versioned_data = {
            "_type": "AssistantState",
            "_version": 0,  # Old version
            "_data": {
                "messages": [],
                "start_id": None,
                "graph_status": None,
            },
        }

        blob_record = await ConversationCheckpointBlob.objects.acreate(
            checkpoint=checkpoint,
            thread_id=thread_id,
            channel="test",
            version="1",
            type="json",
            blob=json.dumps(versioned_data).encode("utf-8"),
        )

        config: RunnableConfig = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
                "checkpoint_ns": "",
            }
        }

        # If the current version is > 0, this should trigger migration
        if migration_registry.current_version > 0:
            await self.checkpointer.aget_tuple(config)
            # Reload and check version was updated
            await blob_record.arefresh_from_db()
            if blob_record.blob:
                new_data = json.loads(blob_record.blob.decode("utf-8"))
            assert new_data["_version"] == migration_registry.current_version


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
