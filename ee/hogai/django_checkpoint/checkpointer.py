import json
from collections.abc import Iterator, Sequence
from typing import Any, Optional

from django.db import transaction
from django.db.models import Q
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.serde.types import TASKS

import ee.models.assistant as models


class DjangoCheckpointer(BaseCheckpointSaver[str]):
    jsonplus_serde = JsonPlusSerializer()

    def _load_writes(self, writes: Sequence[models.CheckpointWrite]) -> list[tuple[str, str, Any]]:
        return (
            [
                (
                    checkpoint_write.task_id,
                    checkpoint_write.channel,
                    self.serde.loads_typed((checkpoint_write.type, checkpoint_write.blob)),
                )
                for checkpoint_write in writes
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
        query = Q()

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

        return models.Checkpoint.objects.filter(query).order_by("-id")

    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
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

        for checkpoint in qs:
            channel_values = []

            loaded_checkpoint = self._load_json(checkpoint.checkpoint)
            if "channel_versions" in loaded_checkpoint:
                query = Q()
                for channel, version in loaded_checkpoint["channel_versions"].items():
                    query |= Q(channel=channel, version=version)
                channel_values = models.CheckpointBlob.objects.filter(
                    Q(thread=checkpoint.thread, checkpoint_ns=checkpoint.checkpoint_ns) & query
                )

            pending_writes = checkpoint.writes.filter(checkpoint_ns=checkpoint.checkpoint_ns).order_by("idx", "task_id")

            if checkpoint.parent_checkpoint is not None:
                pending_sends = checkpoint.parent_checkpoint.writes.filter(
                    checkpoint_ns=checkpoint.checkpoint_ns, channel=TASKS
                ).order_by("task_id", "idx")
            else:
                pending_sends = []

            checkpoint_dict = {
                **loaded_checkpoint,
                "pending_sends": [
                    self.serde.loads_typed((checkpoint_write.type, checkpoint_write.blob))
                    for checkpoint_write in pending_sends
                ],
                "channel_values": {
                    checkpoint_blob.channel: self.serde.loads_typed((checkpoint_blob.type, checkpoint_blob.blob))
                    for checkpoint_blob in channel_values
                    if checkpoint_blob.type != "empty"
                },
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
                self._load_writes(pending_writes),
            )

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
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
        return next(self.list(config), None)

    def put(
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
        configurable = config["configurable"].copy()
        thread_id = configurable.pop("thread_id")
        checkpoint_ns = configurable.pop("checkpoint_ns")
        checkpoint_id = configurable.pop("checkpoint_id", configurable.pop("thread_ts", None))

        checkpoint_copy = checkpoint.copy()
        channel_values = checkpoint_copy.pop("channel_values")
        next_config: RunnableConfig = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

        with transaction.atomic():
            checkpoint, _ = models.Checkpoint.objects.update_or_create(
                id=checkpoint["id"],
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                parent_checkpoint_id=checkpoint_id,
                defaults={
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
                    models.CheckpointBlob(
                        thread=checkpoint.thread,
                        checkpoint_ns=checkpoint_ns,
                        channel=channel,
                        version=version,
                        type=type,
                        blob=blob,
                    )
                )

            models.CheckpointBlob.objects.bulk_create(blobs, ignore_conflicts=True)

        return next_config

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
    ) -> None:
        """Store intermediate writes linked to a checkpoint.

        This method saves intermediate writes associated with a checkpoint to the Postgres database.

        Args:
            config (RunnableConfig): Configuration of the related checkpoint.
            writes (List[Tuple[str, Any]]): List of writes to store.
            task_id (str): Identifier for the task creating the writes.
        """
        writes_to_create = []
        for idx, (channel, value) in enumerate(writes):
            type, blob = self.serde.dumps_typed(value)
            writes_to_create.append(
                models.CheckpointWrite(
                    checkpoint_id=config["configurable"]["checkpoint_id"],
                    checkpoint_ns=config["configurable"]["checkpoint_ns"],
                    task_id=task_id,
                    idx=idx,
                    channel=channel,
                    type=type,
                    blob=blob,
                )
            )

        models.CheckpointWrite.objects.bulk_create(
            writes_to_create,
            update_conflicts=all(w[0] in WRITES_IDX_MAP for w in writes),
            unique_fields=["checkpoint_id", "checkpoint_ns", "task_id", "idx"],
            update_fields=["channel", "type", "blob"],
        )
