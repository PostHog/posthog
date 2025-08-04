import json
import random
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any, Optional, cast
from datetime import datetime, UTC
from posthog.settings import TEST

from django.db import transaction
from django.db.models import Prefetch, Q
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    PendingWrite,
    get_checkpoint_id,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.serde.types import TASKS, ChannelProtocol

from ee.hogai.utils.types import GraphContext, GraphType, VersionMetadata
from ee.models.assistant import ConversationCheckpoint, ConversationCheckpointBlob, ConversationCheckpointWrite
from ee.hogai.django_checkpoint.migrations.registry import registry
from posthog.sync import database_sync_to_async

logger = logging.getLogger(__name__)


class DjangoCheckpointer(BaseCheckpointSaver[str]):
    jsonplus_serde = JsonPlusSerializer()

    def __init__(self, graph_type: GraphType | None = None, graph_context: GraphContext | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not TEST and (not graph_type or not graph_context):
            raise ValueError("graph_type and graph_context must be provided")

        self._graph_metadata = {
            "graph_type": graph_type.value if graph_type else None,
            "context": graph_context.value if graph_context else None,
        }

    def _load_writes(self, writes: Sequence[ConversationCheckpointWrite]) -> list[PendingWrite]:
        return (
            [
                (
                    str(checkpoint_write.task_id),
                    checkpoint_write.channel,
                    self.serde.loads_typed((checkpoint_write.type, checkpoint_write.blob)),
                )
                for checkpoint_write in writes
                if checkpoint_write.type is not None and checkpoint_write.blob is not None
            ]
            if writes
            else []
        )

    def _load_json(self, obj: Any):
        return self.jsonplus_serde.loads(self.jsonplus_serde.dumps(obj))

    def _dump_json(self, obj: Any) -> dict[str, Any]:
        serialized_metadata = self.jsonplus_serde.dumps(obj)
        # NOTE: we're using JSON serializer (not msgpack), so we need to remove null characters before writing
        nulls_removed = serialized_metadata.decode().replace("\\u0000", "")
        return json.loads(nulls_removed)

    def _get_checkpoint_qs(
        self,
        config: Optional[RunnableConfig],
        filter: Optional[dict[str, Any]],
        before: Optional[RunnableConfig],
    ):
        query = Q(checkpoint__isnull=False)

        # construct predicate for config filter
        if config and "configurable" in config:
            thread_id = config["configurable"].get("thread_id")
            query &= Q(thread_id=thread_id)
            checkpoint_ns = config["configurable"].get("checkpoint_ns")
            if checkpoint_ns is not None:
                query &= Q(checkpoint_ns=checkpoint_ns)
            if checkpoint_id := get_checkpoint_id(config):
                query &= Q(id=checkpoint_id)

        # construct predicate for metadata filter
        if filter:
            query &= Q(metadata__contains=filter)

        # construct predicate for `before`
        if before is not None:
            query &= Q(id__lt=get_checkpoint_id(before))

        return (
            ConversationCheckpoint.objects.filter(query)
            .order_by("-id")
            .select_related("parent_checkpoint")
            .prefetch_related(
                Prefetch("writes", queryset=ConversationCheckpointWrite.objects.order_by("idx", "task_id")),
                Prefetch(
                    "parent_checkpoint__writes",
                    queryset=ConversationCheckpointWrite.objects.filter(channel=TASKS).order_by("task_id", "idx"),
                ),
            )
        )

    def _get_checkpoint_channel_values(self, checkpoint: ConversationCheckpoint):
        if not checkpoint.checkpoint:
            return None
        loaded_checkpoint = self._load_json(checkpoint.checkpoint)
        if "channel_versions" not in loaded_checkpoint:
            return None
        query = Q()
        for channel, version in loaded_checkpoint["channel_versions"].items():
            query |= Q(channel=channel, version=version)
        return ConversationCheckpointBlob.objects.filter(
            Q(thread_id=checkpoint.thread_id, checkpoint_ns=checkpoint.checkpoint_ns) & query
        )

    async def _apply_migrations_to_checkpoint(self, checkpoint: ConversationCheckpoint) -> bool:
        """
        Apply all needed migrations to a checkpoint.

        This method:
        1. Determines current checkpoint version from metadata
        2. Gets list of migrations needed to reach current version
        3. Applies migrations in order
        4. Updates migration statistics

        Args:
            checkpoint: ConversationCheckpoint to migrate

        Returns:
            True if any migrations were applied, False otherwise
        """
        # Get current checkpoint version
        metadata = checkpoint.metadata or {}
        current_version = registry.get_checkpoint_version(metadata)

        # Get migrations that need to be applied
        migrations_needed = registry.get_migrations_needed(current_version)

        if not migrations_needed:
            return False

        if not self._graph_metadata["graph_type"] or not self._graph_metadata["context"]:
            return False

        # Apply each migration in order
        migration_applied = False
        for MigrationClass in migrations_needed:
            try:
                # Apply the migration to the checkpoint
                applied = await MigrationClass.apply_to_checkpoint(
                    checkpoint, self.serde, self._graph_metadata["graph_type"], self._graph_metadata["context"]
                )

                if applied:
                    migration_applied = True

            except Exception as e:
                logger.exception(f"Failed to apply migration {MigrationClass.__name__}, error: {e}")
                migration_applied = False
                break

        return migration_applied

    def _add_version_metadata(self, state: dict[str, Any]) -> dict[str, Any]:
        if not registry._migrations:
            return state

        version_metadata = VersionMetadata(
            schema_version=registry.current_version,
            migrated_at=datetime.now(UTC).isoformat(),
            graph_type=GraphType(self._graph_metadata["graph_type"]),
            context=GraphContext(self._graph_metadata["context"]),
        )
        return {**state, "version_metadata": version_metadata.model_dump()}

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """List checkpoints from the database.

        This method retrieves a list of checkpoint tuples from the Postgres database based
        on the provided config. The checkpoints are ordered by checkpoint ID in descending order (newest first).

        Args:
            config (RunnableConfig): The config to use for listing the checkpoints.
            filter (Optional[Dict[str, Any]]): Additional filtering criteria for metadata. Defaults to None.
            before (Optional[RunnableConfig]): If provided, only checkpoints before the specified checkpoint ID are returned. Defaults to None.
            limit (Optional[int]): The maximum number of checkpoints to return. Defaults to None.

        Yields:
            Iterator[CheckpointTuple]: An iterator of checkpoint tuples.
        """
        qs = self._get_checkpoint_qs(config, filter, before)
        if limit:
            qs = qs[:limit]

        async for checkpoint in qs:
            await self._apply_migrations_to_checkpoint(checkpoint)

            channel_values = self._get_checkpoint_channel_values(checkpoint)
            loaded_checkpoint: Checkpoint = self._load_json(checkpoint.checkpoint)

            pending_sends = (
                [
                    self.serde.loads_typed((checkpoint_write.type, checkpoint_write.blob))
                    # Prefetched in `_get_checkpoint_qs`
                    async for checkpoint_write in checkpoint.parent_checkpoint.writes.all()
                ]
                if checkpoint.parent_checkpoint
                else []
            )

            channel_values = (
                {
                    checkpoint_blob.channel: self.serde.loads_typed((checkpoint_blob.type, checkpoint_blob.blob))
                    async for checkpoint_blob in channel_values
                    if checkpoint_blob.type is not None
                    and checkpoint_blob.type != "empty"
                    and checkpoint_blob.blob is not None
                }
                if channel_values is not None
                else {}
            )

            checkpoint_dict: Checkpoint = {
                **loaded_checkpoint,
                "pending_sends": pending_sends,
                "channel_values": channel_values,
            }

            yield CheckpointTuple(
                {
                    "configurable": {
                        "thread_id": checkpoint.thread_id,
                        "checkpoint_ns": checkpoint.checkpoint_ns,
                        "checkpoint_id": checkpoint.id,
                    }
                },
                checkpoint_dict,
                self._load_json(checkpoint.metadata),
                (
                    {
                        "configurable": {
                            "thread_id": checkpoint.thread_id,
                            "checkpoint_ns": checkpoint.checkpoint_ns,
                            "checkpoint_id": checkpoint.parent_checkpoint_id,
                        }
                    }
                    if checkpoint.parent_checkpoint
                    else None
                ),
                # Prefetched in `_get_checkpoint_qs`
                self._load_writes([write async for write in checkpoint.writes.all()]),
            )

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Get a checkpoint tuple from the database.

        This method retrieves a checkpoint tuple from the Postgres database based on the
        provided config. If the config contains a "checkpoint_id" key, the checkpoint with
        the matching thread ID and timestamp is retrieved. Otherwise, the latest checkpoint
        for the given thread ID is retrieved.

        Args:
            config (RunnableConfig): The config to use for retrieving the checkpoint.

        Returns:
            Optional[CheckpointTuple]: The retrieved checkpoint tuple, or None if no matching checkpoint was found.
        """
        return await anext(self.alist(config), None)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return await self._put(config, checkpoint, metadata, new_versions)

    @database_sync_to_async(thread_sensitive=True)
    def _put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Save a checkpoint to the database.

        This method saves a checkpoint to the Postgres database. The checkpoint is associated
        with the provided config and its parent config (if any).

        Args:
            config (RunnableConfig): The config to associate with the checkpoint.
            checkpoint (Checkpoint): The checkpoint to save.
            metadata (CheckpointMetadata): Additional metadata to save with the checkpoint.
            new_versions (ChannelVersions): New channel versions as of this write.

        Returns:
            RunnableConfig: Updated configuration after storing the checkpoint.
        """
        configurable = config["configurable"]
        thread_id: str = configurable["thread_id"]
        checkpoint_id = get_checkpoint_id(config)
        checkpoint_ns: str | None = configurable.get("checkpoint_ns") or ""

        checkpoint_copy = cast(dict[str, Any], checkpoint.copy())
        channel_values = checkpoint_copy.pop("channel_values", {})

        next_config: RunnableConfig = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

        with transaction.atomic():
            updated_checkpoint, _ = ConversationCheckpoint.objects.update_or_create(
                id=checkpoint["id"],
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                defaults={
                    "parent_checkpoint_id": checkpoint_id,
                    "checkpoint": self._dump_json({**checkpoint_copy, "pending_sends": []}),
                    "metadata": self._add_version_metadata(self._dump_json(metadata)),
                },
            )

            blobs = []
            for channel, version in new_versions.items():
                type, blob = (
                    self.serde.dumps_typed(self._add_version_metadata(channel_values[channel]))
                    if channel in channel_values
                    else ("empty", None)
                )
                blobs.append(
                    ConversationCheckpointBlob(
                        checkpoint=updated_checkpoint,
                        thread_id=thread_id,
                        channel=channel,
                        version=str(version),
                        type=type,
                        blob=blob,
                    )
                )

            ConversationCheckpointBlob.objects.bulk_create(blobs, ignore_conflicts=True)
        return next_config

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        return await self._put_writes(config, writes, task_id, task_path)

    @database_sync_to_async(thread_sensitive=True)
    def _put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ):
        """Store intermediate writes linked to a checkpoint.

        This method saves intermediate writes associated with a checkpoint to the Postgres database.

        Args:
            config (RunnableConfig): Configuration of the related checkpoint.
            writes (List[Tuple[str, Any]]): List of writes to store.
            task_id (str): Identifier for the task creating the writes.
        """
        configurable = config["configurable"]
        thread_id: str = configurable["thread_id"]
        checkpoint_id = get_checkpoint_id(config)
        checkpoint_ns: str | None = configurable.get("checkpoint_ns") or ""

        with transaction.atomic():
            # `put_writes` and `put` are concurrently called without guaranteeing the call order
            # so we need to ensure the checkpoint is created before creating writes.
            # Thread.lock() will prevent race conditions though to the same checkpoints within a single pod.
            checkpoint, _ = ConversationCheckpoint.objects.get_or_create(
                id=checkpoint_id, thread_id=thread_id, checkpoint_ns=checkpoint_ns
            )

            writes_to_create = []
            for idx, (channel, value) in enumerate(writes):
                type, blob = self.serde.dumps_typed(self._add_version_metadata(value))
                writes_to_create.append(
                    ConversationCheckpointWrite(
                        checkpoint=checkpoint,
                        task_id=task_id,
                        idx=idx,
                        channel=channel,
                        type=type,
                        blob=blob,
                    )
                )

            ConversationCheckpointWrite.objects.bulk_create(
                writes_to_create,
                update_conflicts=all(w[0] in WRITES_IDX_MAP for w in writes),
                unique_fields=["checkpoint", "task_id", "idx"],
                update_fields=["channel", "type", "blob"],
            )

    def get_next_version(self, current: Optional[str | int], channel: ChannelProtocol) -> str:
        if current is None:
            current_v = 0
        elif isinstance(current, int):
            current_v = current
        else:
            current_v = int(current.split(".")[0])
        next_v = current_v + 1
        next_h = random.random()
        return f"{next_v:032}.{next_h:016}"
