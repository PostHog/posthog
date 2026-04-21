import time

import pyarrow as pa

from products.data_warehouse.backend.webhook_consumer.config import WebhookConsumerConfig


class SchemaBuffer:
    def __init__(self, team_id: int, schema_id: str):
        self.team_id = team_id
        self.schema_id = schema_id
        self._payloads: list[str] = []
        self.total_size_bytes: int = 0

    def add(self, payload_json: str) -> int:
        """Add a message and return its estimated size in bytes."""

        size = len(payload_json.encode("utf-8"))
        self._payloads.append(payload_json)
        self.total_size_bytes += size
        return size

    def to_arrow_table(self) -> pa.Table:
        count = len(self._payloads)
        return pa.table(
            {
                "team_id": pa.array([self.team_id] * count, type=pa.int64()),
                "schema_id": pa.array([self.schema_id] * count, type=pa.utf8()),
                "payload_json": pa.array(self._payloads, type=pa.utf8()),
            }
        )

    def clear(self) -> None:
        self._payloads.clear()
        self.total_size_bytes = 0

    @property
    def payloads(self) -> list[str]:
        return self._payloads

    def __len__(self) -> int:
        return len(self._payloads)


class BatchBuffer:
    def __init__(self, config: WebhookConsumerConfig):
        self._config = config
        self._buffers: dict[str, SchemaBuffer] = {}
        self._total_messages: int = 0
        self._total_size_bytes: int = 0
        self._last_flush_time: float = time.monotonic()

    def add(self, team_id: int, schema_id: str, payload_json: str) -> None:
        key = f"{team_id}:{schema_id}"
        if key not in self._buffers:
            self._buffers[key] = SchemaBuffer(team_id, schema_id)
        size = self._buffers[key].add(payload_json)
        self._total_messages += 1
        self._total_size_bytes += size

    def should_flush(self) -> str | None:
        """Return the flush trigger reason, or None if no flush is needed."""
        if self._total_messages == 0:
            return None

        if time.monotonic() - self._last_flush_time >= self._config.flush_interval_seconds:
            return "time"

        if self._total_messages >= self._config.max_batch_messages:
            return "count"

        if self._total_size_bytes >= self._config.max_buffer_size_bytes:
            return "size"

        return None

    def get_buffers(self) -> dict[str, SchemaBuffer]:
        return {k: v for k, v in self._buffers.items() if len(v) > 0}

    def clear(self) -> None:
        self._buffers.clear()
        self._total_messages = 0
        self._total_size_bytes = 0
        self._last_flush_time = time.monotonic()

    @property
    def total_messages(self) -> int:
        return self._total_messages

    @property
    def total_size_bytes(self) -> int:
        return self._total_size_bytes
