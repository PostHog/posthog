import time
from typing import Any, cast

import pyarrow as pa

from products.data_warehouse.backend.webhook_consumer.buffer import BatchBuffer, SchemaBuffer
from products.data_warehouse.backend.webhook_consumer.config import WebhookConsumerConfig


def _make_config(**kwargs) -> WebhookConsumerConfig:
    defaults = {
        "input_topic": "test-topic",
        "consumer_group": "test-group",
        "dlq_topic": "test-dlq",
    }
    defaults.update(kwargs)
    return WebhookConsumerConfig(**cast(Any, defaults))


class TestSchemaBuffer:
    def test_add_message(self):
        buf = SchemaBuffer(team_id=1, schema_id="schema-a")
        size = buf.add('{"key": "value"}')

        assert len(buf) == 1
        assert buf.total_size_bytes == size
        assert size > 0

    def test_add_multiple_messages(self):
        buf = SchemaBuffer(team_id=1, schema_id="schema-a")
        buf.add('{"a": 1}')
        buf.add('{"b": 2}')

        assert len(buf) == 2

    def test_to_arrow_table_schema(self):
        buf = SchemaBuffer(team_id=42, schema_id="schema-x")
        buf.add('{"event": "test"}')

        table = buf.to_arrow_table()

        assert isinstance(table, pa.Table)
        assert table.num_rows == 1
        assert table.schema.field("team_id").type == pa.int64()
        assert table.schema.field("schema_id").type == pa.utf8()
        assert table.schema.field("payload_json").type == pa.utf8()

    def test_to_arrow_table_values(self):
        buf = SchemaBuffer(team_id=42, schema_id="schema-x")
        buf.add('{"event": "test"}')
        buf.add('{"event": "test2"}')

        table = buf.to_arrow_table()

        assert table.column("team_id").to_pylist() == [42, 42]
        assert table.column("schema_id").to_pylist() == ["schema-x", "schema-x"]
        assert table.column("payload_json").to_pylist() == ['{"event": "test"}', '{"event": "test2"}']

    def test_clear(self):
        buf = SchemaBuffer(team_id=1, schema_id="schema-a")
        buf.add('{"a": 1}')
        buf.clear()

        assert len(buf) == 0
        assert buf.total_size_bytes == 0


class TestBatchBuffer:
    def test_add_routes_by_schema_id(self):
        config = _make_config()
        buf = BatchBuffer(config)

        buf.add(1, "schema-a", '{"a": 1}')
        buf.add(1, "schema-b", '{"b": 1}')
        buf.add(1, "schema-a", '{"a": 2}')

        buffers = buf.get_buffers()
        assert len(buffers) == 2
        assert len(buffers["1:schema-a"]) == 2
        assert len(buffers["1:schema-b"]) == 1

    def test_add_routes_by_team_and_schema(self):
        config = _make_config()
        buf = BatchBuffer(config)

        buf.add(1, "schema-a", '{"a": 1}')
        buf.add(2, "schema-a", '{"a": 2}')

        buffers = buf.get_buffers()
        assert len(buffers) == 2
        assert "1:schema-a" in buffers
        assert "2:schema-a" in buffers

    def test_total_messages(self):
        config = _make_config()
        buf = BatchBuffer(config)

        buf.add(1, "s", '{"a": 1}')
        buf.add(1, "s", '{"a": 2}')
        buf.add(2, "s", '{"a": 3}')

        assert buf.total_messages == 3

    def test_total_size_bytes(self):
        config = _make_config()
        buf = BatchBuffer(config)
        payload = '{"key": "value"}'

        buf.add(1, "s", payload)

        assert buf.total_size_bytes == len(payload.encode("utf-8"))

    def test_should_flush_below_thresholds(self):
        config = _make_config(
            flush_interval_seconds=60.0, max_batch_messages=10_000, max_buffer_size_bytes=50 * 1024 * 1024
        )
        buf = BatchBuffer(config)
        buf.add(1, "s", '{"a": 1}')

        assert buf.should_flush() is None

    def test_should_flush_by_time(self):
        config = _make_config(
            flush_interval_seconds=0.0, max_batch_messages=10_000, max_buffer_size_bytes=50 * 1024 * 1024
        )
        buf = BatchBuffer(config)
        buf.add(1, "s", '{"a": 1}')
        time.sleep(0.01)

        assert buf.should_flush() == "time"

    def test_should_flush_by_message_count(self):
        config = _make_config(max_batch_messages=3, flush_interval_seconds=9999)
        buf = BatchBuffer(config)

        buf.add(1, "s", '{"a": 1}')
        buf.add(1, "s", '{"a": 2}')
        assert buf.should_flush() is None

        buf.add(1, "s", '{"a": 3}')
        assert buf.should_flush() == "count"

    def test_should_flush_by_size(self):
        config = _make_config(max_buffer_size_bytes=50, flush_interval_seconds=9999, max_batch_messages=999999)
        buf = BatchBuffer(config)

        # Each payload is ~16 bytes
        buf.add(1, "s", '{"a": "value1"}')
        assert buf.should_flush() is None

        buf.add(1, "s", '{"a": "value2"}')
        buf.add(1, "s", '{"a": "value3"}')
        buf.add(1, "s", '{"a": "value4"}')
        assert buf.should_flush() == "size"

    def test_should_flush_empty_buffer(self):
        config = _make_config(flush_interval_seconds=0.0)
        buf = BatchBuffer(config)
        time.sleep(0.01)

        assert buf.should_flush() is None

    def test_clear_resets_all_state(self):
        config = _make_config()
        buf = BatchBuffer(config)
        buf.add(1, "s", '{"a": 1}')
        buf.add(2, "s", '{"b": 1}')

        buf.clear()

        assert buf.total_messages == 0
        assert buf.total_size_bytes == 0
        assert len(buf.get_buffers()) == 0

    def test_get_buffers_excludes_empty(self):
        config = _make_config()
        buf = BatchBuffer(config)
        buf.add(1, "s", '{"a": 1}')

        buffers = buf.get_buffers()
        assert len(buffers) == 1

        # After clear, should be empty
        buf.clear()
        assert len(buf.get_buffers()) == 0
