import json
import random
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any, Optional, cast

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

from ee.models.assistant import ConversationCheckpoint, ConversationCheckpointBlob, ConversationCheckpointWrite
from posthog.sync import database_sync_to_async


class DjangoCheckpointer(BaseCheckpointSaver[str]):
    jsonplus_serde = JsonPlusSerializer()

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
        start_time = time.time()
        thread_id = config["configurable"]["thread_id"]

        # Track async-to-sync call overhead
        sync_call_start = time.time()
        result, result_str = await self._put(config, checkpoint, metadata, new_versions, sync_call_start)
        sync_call_duration = time.time() - sync_call_start

        total_duration = time.time() - start_time
        print(
            f"aput: {result_str}, total_duration_ms={round(total_duration * 1000, 2)}, sync_call_duration_ms={round(sync_call_duration * 1000, 2)}, channel_count={len(new_versions)}"
        )
        return result

    @database_sync_to_async(thread_sensitive=True)
    def _put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
        start_time: float = 0,
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
        db_start_time = time.time()

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
            transaction_start_time = time.time()

            transaction_end_time_time = time.time() - transaction_start_time
            # Track checkpoint update operation
            checkpoint_update_start = time.time()
            updated_checkpoint, _ = ConversationCheckpoint.objects.update_or_create(
                id=checkpoint["id"],
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                defaults={
                    "parent_checkpoint_id": checkpoint_id,
                    "checkpoint": self._dump_json({**checkpoint_copy, "pending_sends": []}),
                    "metadata": self._dump_json(metadata),
                },
            )
            checkpoint_update_duration = time.time() - checkpoint_update_start

            # Track blob creation operation
            blob_creation_start = time.time()
            blobs = []
            for channel, version in new_versions.items():
                type, blob = (
                    self.serde.dumps_typed(channel_values[channel]) if channel in channel_values else ("empty", None)
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
            blob_creation_duration = time.time() - blob_creation_start

        db_total_duration = time.time() - db_start_time

        return (
            next_config,
            f"thread_id={thread_id}, checkpoint_id={checkpoint_id}, time_to_start_ms={round((db_start_time - start_time) * 1000, 2)}, db_total_ms={round(db_total_duration * 1000, 2)}, transaction_end_time_time={round(transaction_end_time_time * 1000, 2)}, checkpoint_update_ms={round(checkpoint_update_duration * 1000, 2)}, blob_creation_ms={round(blob_creation_duration * 1000, 2)}",
        )

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        start_time = time.time()
        thread_id = config["configurable"]["thread_id"]

        # Track async-to-sync call overhead
        sync_call_start = time.time()
        result = await self._put_writes(config, writes, task_id, task_path, sync_call_start)
        sync_call_duration = time.time() - sync_call_start

        total_duration = time.time() - start_time
        print(
            f"aput_writes: {result}, total_duration_ms={round(total_duration * 1000, 2)}, sync_call_duration_ms={round(sync_call_duration * 1000, 2)}, write_count={len(writes)}"
        )
        return None

    @database_sync_to_async(thread_sensitive=True)
    def _put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
        start_time: float = 0,
    ):
        """Store intermediate writes linked to a checkpoint.

        This method saves intermediate writes associated with a checkpoint to the Postgres database.

        Args:
            config (RunnableConfig): Configuration of the related checkpoint.
            writes (List[Tuple[str, Any]]): List of writes to store.
            task_id (str): Identifier for the task creating the writes.
        """
        db_start_time = time.time()

        configurable = config["configurable"]
        thread_id: str = configurable["thread_id"]
        checkpoint_id = get_checkpoint_id(config)
        checkpoint_ns: str | None = configurable.get("checkpoint_ns") or ""

        transaction_start_time = time.time()
        with transaction.atomic():
            transaction_end_time_time = time.time() - transaction_start_time
            # Track checkpoint get_or_create operation
            checkpoint_lookup_start = time.time()
            checkpoint, _ = ConversationCheckpoint.objects.get_or_create(
                id=checkpoint_id, thread_id=thread_id, checkpoint_ns=checkpoint_ns
            )
            checkpoint_lookup_duration = time.time() - checkpoint_lookup_start

            # Track write preparation
            write_prep_start = time.time()
            writes_to_create = []
            for idx, (channel, value) in enumerate(writes):
                type, blob = self.serde.dumps_typed(value)
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
            write_prep_duration = time.time() - write_prep_start

            # Track bulk create operation
            bulk_create_start = time.time()
            ConversationCheckpointWrite.objects.bulk_create(
                writes_to_create,
                update_conflicts=all(w[0] in WRITES_IDX_MAP for w in writes),
                unique_fields=["checkpoint", "task_id", "idx"],
                update_fields=["channel", "type", "blob"],
            )
            bulk_create_duration = time.time() - bulk_create_start

        db_total_duration = time.time() - db_start_time
        return f"thread_id={thread_id}, checkpoint_id={checkpoint_id}, task_id={task_id}, time_to_start_ms={round((db_start_time - start_time) * 1000, 2)}, db_total_ms={round(db_total_duration * 1000, 2)}, transaction_end_time_time={round(transaction_end_time_time * 1000, 2)}, checkpoint_lookup_ms={round(checkpoint_lookup_duration * 1000, 2)}, write_prep_ms={round(write_prep_duration * 1000, 2)}, bulk_create_ms={round(bulk_create_duration * 1000, 2)}"

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
