import json
import random
from collections.abc import AsyncIterator, Sequence
from typing import Any, Optional, cast

from django.db import transaction
from django.db.models import Prefetch, Q

from langchain_core.load.serializable import Serializable
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    PendingWrite,
    get_checkpoint_id,
)
from langgraph.checkpoint.serde.types import TASKS, ChannelProtocol

from posthog.sync import database_sync_to_async

from products.posthog_ai.backend.models.assistant import (
    ConversationCheckpoint,
    ConversationCheckpointBlob,
    ConversationCheckpointWrite,
)


def _json_default(obj: Any) -> Any:
    """JSON default handler that preserves LangChain constructor markers.

    Replicates the behaviour of JsonPlusSerializer.dumps (removed in checkpoint 3.x)
    for the subset of types that appear in checkpoint metadata.
    """
    if isinstance(obj, Serializable):
        return obj.to_json()
    elif hasattr(obj, "model_dump") and callable(obj.model_dump):
        return {
            "lc": 2,
            "type": "constructor",
            "id": (*obj.__class__.__module__.split("."), obj.__class__.__name__),
            "method": (None, "model_construct"),
            "kwargs": obj.model_dump(),
        }
    elif isinstance(obj, (set, frozenset)):
        return list(obj)
    elif isinstance(obj, (bytes, bytearray)):
        return obj.hex()
    else:
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class DjangoCheckpointer(BaseCheckpointSaver[str]):

    def _load_writes(self, writes: Sequence[ConversationCheckpointWrite]) -> list[PendingWrite]:
        return (
            [
                (
                    str(checkpoint_write.task_id),
                    checkpoint_write.channel,
                    self.serde.loads_typed((checkpoint_write.type, bytes(checkpoint_write.blob))),
                )
                for checkpoint_write in writes
                if checkpoint_write.type is not None and checkpoint_write.blob is not None
            ]
            if writes
            else []
        )

    def _dump_json(self, obj: Any) -> dict[str, Any]:
        serialized = json.dumps(obj, default=_json_default, ensure_ascii=False)
        # Remove null characters before writing to the database
        nulls_removed = serialized.replace("\\u0000", "")
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
        if "channel_versions" not in checkpoint.checkpoint:
            return None
        query = Q()
        for channel, version in checkpoint.checkpoint["channel_versions"].items():
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
            loaded_checkpoint: Checkpoint = checkpoint.checkpoint

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

            # langgraph-checkpoint 2.1 dropped `pending_sends` from the Checkpoint TypedDict, but the langgraph runtime still consumes it via `.get()`, so keep emitting it as an extra key
            checkpoint_dict = cast(
                Checkpoint,
                {
                    **loaded_checkpoint,
                    "pending_sends": pending_sends,
                    "channel_values": channel_values,
                },
            )

            yield CheckpointTuple(
                {
                    "configurable": {
                        "thread_id": checkpoint.thread_id,
                        "checkpoint_ns": checkpoint.checkpoint_ns,
                        "checkpoint_id": checkpoint.id,
                    }
                },
                checkpoint_dict,
                checkpoint.metadata,
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
            # nosemgrep: idor-lookup-without-team (internal LangGraph checkpoint)
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
            # nosemgrep: idor-lookup-without-team (internal LangGraph checkpoint)
            checkpoint, _ = ConversationCheckpoint.objects.get_or_create(
                id=checkpoint_id, thread_id=thread_id, checkpoint_ns=checkpoint_ns
            )

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

            # Setting update_conflicts=True to handle resume-from-interrupt scenarios.
            # When a tool calls interrupt() and later resumes, LangGraph may write to the
            # same (checkpoint_id, task_id, idx) combination. We want to ensure we update
            # existing writes on duplicate key.
            ConversationCheckpointWrite.objects.bulk_create(
                writes_to_create,
                update_conflicts=True,
                unique_fields=["checkpoint", "task_id", "idx"],
                update_fields=["channel", "type", "blob"],
            )

    # `channel` is typed `None` (deprecated) in the 2.1 base class, but langgraph 0.4 still passes a real channel object, so accept both
    def get_next_version(self, current: Optional[str | int], channel: Optional[ChannelProtocol] = None) -> str:
        if current is None:
            current_v = 0
        elif isinstance(current, int):
            current_v = current
        else:
            current_v = int(current.split(".")[0])
        next_v = current_v + 1
        next_h = random.random()
        return f"{next_v:032}.{next_h:016}"
