import re
import json
import random
import decimal
import pathlib
import dataclasses
from collections import deque
from collections.abc import AsyncIterator, Sequence
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from ipaddress import IPv4Address, IPv4Interface, IPv4Network, IPv6Address, IPv6Interface, IPv6Network
from typing import Any, Optional, cast
from uuid import UUID
from zoneinfo import ZoneInfo

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
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.serde.types import TASKS, ChannelProtocol, SendProtocol

from posthog.sync import database_sync_to_async

from ee.models.assistant import ConversationCheckpoint, ConversationCheckpointBlob, ConversationCheckpointWrite


def _json_default(serde: JsonPlusSerializer, obj: Any) -> str | dict[str, Any]:
    """JSON encoder hook for checkpoint metadata.

    Replicates the old JsonPlusSerializer._default() method that was removed
    in langgraph-checkpoint 3.0+. Converts special Python types to lc:2
    constructor dicts for JSON storage.
    """
    if isinstance(obj, Serializable):
        return cast(dict[str, Any], obj.to_json())
    elif hasattr(obj, "model_dump") and callable(obj.model_dump):
        return serde._encode_constructor_args(obj.__class__, method=(None, "model_construct"), kwargs=obj.model_dump())
    elif hasattr(obj, "dict") and callable(obj.dict):
        return serde._encode_constructor_args(obj.__class__, method=(None, "construct"), kwargs=obj.dict())
    elif hasattr(obj, "_asdict") and callable(obj._asdict):
        return serde._encode_constructor_args(obj.__class__, kwargs=obj._asdict())
    elif isinstance(obj, pathlib.Path):
        return serde._encode_constructor_args(pathlib.Path, args=obj.parts)
    elif isinstance(obj, re.Pattern):
        return serde._encode_constructor_args(re.compile, args=(obj.pattern, obj.flags))
    elif isinstance(obj, UUID):
        return serde._encode_constructor_args(UUID, args=(obj.hex,))
    elif isinstance(obj, decimal.Decimal):
        return serde._encode_constructor_args(decimal.Decimal, args=(str(obj),))
    elif isinstance(obj, datetime):
        return serde._encode_constructor_args(datetime, method="fromisoformat", args=(obj.isoformat(),))
    elif isinstance(obj, timezone):
        return serde._encode_constructor_args(timezone, args=obj.__getinitargs__())  # type: ignore[attr-defined]
    elif isinstance(obj, ZoneInfo):
        return serde._encode_constructor_args(ZoneInfo, args=(obj.key,))
    elif isinstance(obj, timedelta):
        return serde._encode_constructor_args(timedelta, args=(obj.days, obj.seconds, obj.microseconds))
    elif isinstance(obj, date):
        return serde._encode_constructor_args(date, args=(obj.year, obj.month, obj.day))
    elif isinstance(obj, time):
        return serde._encode_constructor_args(
            time, args=(obj.hour, obj.minute, obj.second, obj.microsecond, obj.tzinfo), kwargs={"fold": obj.fold}
        )
    elif isinstance(obj, (set, frozenset, deque)):
        return serde._encode_constructor_args(type(obj), args=(tuple(obj),))
    elif isinstance(obj, (IPv4Address, IPv4Interface, IPv4Network, IPv6Address, IPv6Interface, IPv6Network)):
        return serde._encode_constructor_args(obj.__class__, args=(str(obj),))
    elif isinstance(obj, Enum):
        return serde._encode_constructor_args(obj.__class__, args=(obj.value,))
    elif isinstance(obj, SendProtocol):
        return serde._encode_constructor_args(obj.__class__, kwargs={"node": obj.node, "arg": obj.arg})
    elif isinstance(obj, (bytes, bytearray)):
        return serde._encode_constructor_args(obj.__class__, method="fromhex", args=(obj.hex(),))
    elif dataclasses.is_dataclass(obj):
        return serde._encode_constructor_args(
            obj.__class__, kwargs={field.name: getattr(obj, field.name) for field in dataclasses.fields(obj)}
        )
    elif isinstance(obj, BaseException):
        return repr(obj)
    else:
        raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


class DjangoCheckpointer(BaseCheckpointSaver[str]):
    jsonplus_serde = JsonPlusSerializer(allowed_json_modules=True)

    def __init__(self, **kwargs: Any) -> None:
        # NOTE: allowed_msgpack_modules is intentionally left at the default (True)
        # rather than strict mode (None). Strict mode blocks deserialization of
        # PostHog's custom Pydantic message types from msgpack, and langgraph 0.4.10
        # doesn't support automatic allowlist derivation from state schemas.
        # The upgrade to langgraph-checkpoint 4.0.1 still provides:
        # - pickle_fallback=False by default (blocks pickle deserialization)
        # - Deprecation warnings for unregistered ext types
        # - LANGGRAPH_STRICT_MSGPACK env var support for future strict enforcement
        super().__init__(serde=JsonPlusSerializer(allowed_json_modules=True), **kwargs)

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
        serialized = json.dumps(
            obj, default=lambda o: _json_default(self.jsonplus_serde, o), ensure_ascii=False
        ).encode("utf-8", "ignore")
        return json.loads(serialized, object_hook=self.jsonplus_serde._reviver)

    def _dump_json(self, obj: Any) -> dict[str, Any]:
        serialized_metadata = json.dumps(
            obj, default=lambda o: _json_default(self.jsonplus_serde, o), ensure_ascii=False
        ).encode("utf-8", "ignore")
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

    def get_next_version(self, current: Optional[str | int], channel: ChannelProtocol | None) -> str:
        if current is None:
            current_v = 0
        elif isinstance(current, int):
            current_v = current
        else:
            current_v = int(current.split(".")[0])
        next_v = current_v + 1
        next_h = random.random()
        return f"{next_v:032}.{next_h:016}"
