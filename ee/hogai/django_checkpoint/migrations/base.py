import logging
from abc import ABC, abstractmethod
from datetime import datetime, UTC
from typing import Any

from ee.hogai.utils.types import GraphContext, GraphType, VersionMetadata
from .registry import registry

from ee.models.assistant import ConversationCheckpoint, ConversationCheckpointBlob, ConversationCheckpointWrite

logger = logging.getLogger(__name__)


class BaseMigration(ABC):
    """
    Abstract base class for all checkpoint migrations.

    This class provides common functionality for:
    - Blob and write I/O operations
    - Checkpoint metadata management
    - Migration orchestration

    Subclasses must implement:
    - needs_migration(): Detection logic for this migration
    - apply_to_state_object(): State transformation logic
    """

    @classmethod
    def get_version(cls) -> int:
        """
        Get the version number for this migration class.

        Returns:
            Version number for this migration
        """
        return registry.get_version_for_class(cls)

    @staticmethod
    @abstractmethod
    def needs_migration(state_obj: Any) -> bool:
        """
        Check if a state object needs this specific migration.

        This is migration-specific logic that determines whether
        this migration should be applied to a given state object.

        Args:
            state_obj: Decoded state object from checkpoint blob or metadata

        Returns:
            True if this migration is needed, False otherwise
        """
        pass

    @staticmethod
    @abstractmethod
    def apply_to_state_object(state_obj: Any, graph_type: GraphType, context: GraphContext) -> Any:
        """
        Apply this migration to a state object.

        This is the core transformation logic that each migration
        implements to transform state objects.

        Args:
            state_obj: The state object to migrate
            graph_type: Graph type for migration context
            context: Context for migration context

        Returns:
            Migrated state object
        """
        pass

    @classmethod
    async def apply_to_blob_or_write(
        cls,
        object: ConversationCheckpointBlob | ConversationCheckpointWrite,
        checkpointer_serde,
        graph_type: GraphType,
        context: GraphContext,
    ) -> bool:
        """
        Apply this migration to a checkpoint blob and save it back to database.

        Args:
            object: ConversationCheckpointBlob or ConversationCheckpointWrite to migrate
            checkpointer_serde: Serializer from checkpointer
            graph_type: Graph type for migration context
            context: Context for migration context

        Returns:
            True if migration was applied and saved, False if no migration needed
        """
        # Skip empty or null blobs
        if not object.blob or object.type in ["empty", "null", None]:
            return False

        try:
            # Decode the blob data
            decoded_data = checkpointer_serde.loads_typed((object.type, object.blob))

            # Check if migration is needed (migration-specific logic)
            if not cls.needs_migration(decoded_data):
                return False

            # Apply migration (migration-specific logic)
            migrated_data = cls.apply_to_state_object(decoded_data, graph_type, context)

            # Re-encode the migrated data
            new_type, new_blob = checkpointer_serde.dumps_typed(migrated_data)

            # Save back to database
            object.type = new_type
            object.blob = new_blob
            await object.asave(update_fields=["type", "blob"])

            logger.info(
                f"{cls.__name__}: Successfully migrated and saved checkpoint blob {object.id} "
                f"({object.channel}, {context}, v{cls.get_version()})"
            )

            return True

        except Exception as e:
            logger.exception(f"Failed to migrate checkpoint blob {object.id}, error: {e}")
            return False

    @classmethod
    async def apply_to_checkpoint(
        cls, checkpoint: ConversationCheckpoint, checkpointer_serde, graph_type: GraphType, context: GraphContext
    ) -> bool:
        """
        Apply this migration to an entire checkpoint (metadata + blobs + writes).

        This orchestrates the migration of a complete checkpoint by:
        1. Checking if migration is already applied
        2. Detecting graph context
        3. Migrating blobs and writes
        4. Updating checkpoint metadata

        Args:
            checkpoint: ConversationCheckpoint to migrate
            checkpointer_serde: Serializer from checkpointer

        Returns:
            Tuple of (migration_applied, migration_stats)
        """
        # Check if checkpoint is already migrated to this version or higher
        metadata = checkpoint.metadata or {}
        version_info = metadata.get("version_metadata", {})
        current_schema_version = version_info.get("schema_version", 0)

        if current_schema_version >= cls.get_version():
            return False

        if hasattr(cls, "detect_graph_context"):
            # Specific to migration 0001, we overwrite graph_type and context
            # detecting them from the checkpoint
            graph_type, context = cls.detect_graph_context(checkpoint)

        migration_applied = False

        # Migrate all blobs in this checkpoint
        async for blob in checkpoint.blobs.all():
            if await cls.apply_to_blob_or_write(blob, checkpointer_serde, graph_type, context):
                migration_applied = True

        # Migrate all writes in this checkpoint
        async for write in checkpoint.writes.all():
            if await cls.apply_to_blob_or_write(write, checkpointer_serde, graph_type, context):
                migration_applied = True

        # Update checkpoint metadata to mark this migration as complete
        version = cls.get_version()
        if migration_applied or current_schema_version < version:
            updated_metadata = metadata.copy()
            updated_metadata["version_metadata"] = VersionMetadata(
                schema_version=version,
                migrated_at=datetime.now(UTC).isoformat(),
                graph_type=graph_type,
                context=context,
            ).model_dump()

            checkpoint.metadata = updated_metadata
            await checkpoint.asave(update_fields=["metadata"])

        return migration_applied
