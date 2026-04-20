import json
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.data_warehouse.backend.webhook_consumer.config import WebhookConsumerConfig
from products.data_warehouse.backend.webhook_consumer.consumer import WebhookS3Sink


def _make_config(**kwargs) -> WebhookConsumerConfig:
    defaults: dict[str, Any] = {
        "input_topic": "test-topic",
        "consumer_group": "test-group",
        "dlq_topic": "test-dlq",
        "flush_interval_seconds": 9999,
        "max_batch_messages": 9999,
        "max_buffer_size_bytes": 999999,
        "poll_timeout_seconds": 0.1,
        "poll_batch_size": 100,
    }
    defaults.update(kwargs)
    return WebhookConsumerConfig(**defaults)


def _make_consumer(**kwargs) -> WebhookS3Sink:
    defaults: dict = {
        "config": _make_config(),
        "kafka_hosts": ["localhost:9092"],
        "kafka_security_protocol": "PLAINTEXT",
    }
    defaults.update(kwargs)
    return WebhookS3Sink(**defaults)


def _make_kafka_message(value: dict | bytes | None = None, error=None) -> MagicMock:
    msg = MagicMock()
    msg.error.return_value = error
    if isinstance(value, dict):
        msg.value.return_value = json.dumps(value).encode("utf-8")
    elif isinstance(value, bytes):
        msg.value.return_value = value
    else:
        msg.value.return_value = value
    return msg


class TestWebhookS3SinkConfig:
    def test_consumer_uses_latest_offset_reset(self):
        consumer = _make_consumer()

        with patch("products.data_warehouse.backend.webhook_consumer.consumer.ConfluentConsumer") as mock_consumer_cls:
            mock_consumer_cls.return_value = MagicMock()
            consumer._create_consumer()

            config = mock_consumer_cls.call_args[0][0]
            assert config["auto.offset.reset"] == "latest"

    def test_auto_commit_disabled(self):
        consumer = _make_consumer()

        with patch("products.data_warehouse.backend.webhook_consumer.consumer.ConfluentConsumer") as mock_consumer_cls:
            mock_consumer_cls.return_value = MagicMock()
            consumer._create_consumer()

            config = mock_consumer_cls.call_args[0][0]
            assert config["enable.auto.commit"] is False

    def test_subscribe_with_correct_topic(self):
        consumer = _make_consumer(config=_make_config(input_topic="my-topic"))

        with patch("products.data_warehouse.backend.webhook_consumer.consumer.ConfluentConsumer") as mock_consumer_cls:
            mock_instance = MagicMock()
            mock_consumer_cls.return_value = mock_instance
            consumer._create_consumer()

            mock_instance.subscribe.assert_called_once_with(
                ["my-topic"],
                on_assign=consumer._on_assign,
                on_revoke=consumer._on_revoke,
            )

    def test_uses_provided_kafka_hosts(self):
        consumer = _make_consumer(kafka_hosts=["host1:9092", "host2:9092"])

        with patch("products.data_warehouse.backend.webhook_consumer.consumer.ConfluentConsumer") as mock_consumer_cls:
            mock_consumer_cls.return_value = MagicMock()
            consumer._create_consumer()

            config = mock_consumer_cls.call_args[0][0]
            assert config["bootstrap.servers"] == "host1:9092,host2:9092"


class TestWebhookS3SinkMessageProcessing:
    def test_valid_message_gets_buffered(self):
        consumer = _make_consumer()
        raw = json.dumps({"team_id": 1, "schema_id": "schema-a", "payload": '{"event": "test"}'}).encode("utf-8")

        consumer._process_message(raw)

        assert consumer._buffer.total_messages == 1

    @parameterized.expand(
        [
            ("missing_team_id", {"schema_id": "s", "payload": "p"}),
            ("missing_schema_id", {"team_id": 1, "payload": "p"}),
            ("missing_payload", {"team_id": 1, "schema_id": "s"}),
            ("team_id_is_string", {"team_id": "1", "schema_id": "s", "payload": "p"}),
            ("team_id_is_float", {"team_id": 1.5, "schema_id": "s", "payload": "p"}),
            ("schema_id_is_int", {"team_id": 1, "schema_id": 123, "payload": "p"}),
            ("schema_id_is_empty", {"team_id": 1, "schema_id": "", "payload": "p"}),
            ("payload_is_int", {"team_id": 1, "schema_id": "s", "payload": 123}),
            ("payload_is_dict", {"team_id": 1, "schema_id": "s", "payload": {"nested": True}}),
        ]
    )
    def test_invalid_message_sent_to_dlq(self, _name, message):
        consumer = _make_consumer()
        consumer._dlq_producer = MagicMock()
        raw = json.dumps(message).encode("utf-8")

        consumer._process_message(raw)

        assert consumer._buffer.total_messages == 0
        consumer._dlq_producer.produce.assert_called_once()
        consumer._dlq_producer.flush.assert_called_once()

    def test_unparseable_json_sent_to_dlq(self):
        consumer = _make_consumer()
        consumer._dlq_producer = MagicMock()

        consumer._process_message(b"not json")

        assert consumer._buffer.total_messages == 0
        consumer._dlq_producer.produce.assert_called_once()

    def test_invalid_utf8_sent_to_dlq(self):
        consumer = _make_consumer()
        consumer._dlq_producer = MagicMock()

        consumer._process_message(b"\x80\x81\x82")

        assert consumer._buffer.total_messages == 0
        consumer._dlq_producer.produce.assert_called_once()


class TestWebhookS3SinkFlush:
    @patch("products.data_warehouse.backend.webhook_consumer.consumer.WebhookParquetWriter")
    def test_flush_writes_parquet_per_schema(self, mock_writer_cls):
        mock_writer = MagicMock()
        mock_writer.write.return_value = "s3://bucket/path.parquet"
        mock_writer_cls.return_value = mock_writer

        consumer = _make_consumer()
        consumer._consumer = MagicMock()

        consumer._buffer.add(1, "schema-a", '{"a": 1}')
        consumer._buffer.add(1, "schema-a", '{"a": 2}')
        consumer._buffer.add(1, "schema-b", '{"b": 1}')

        consumer._flush_all("test")

        assert mock_writer.write.call_count == 2
        write_calls = {c.kwargs.get("schema_id") or c.args[2]: c for c in mock_writer.write.call_args_list}
        assert "schema-a" in write_calls
        assert "schema-b" in write_calls

    @patch("products.data_warehouse.backend.webhook_consumer.consumer.WebhookParquetWriter")
    def test_flush_commits_offsets_after_writes(self, mock_writer_cls):
        mock_writer = MagicMock()
        mock_writer.write.return_value = "s3://bucket/path.parquet"
        mock_writer_cls.return_value = mock_writer

        consumer = _make_consumer()
        mock_kafka_consumer = MagicMock()
        consumer._consumer = mock_kafka_consumer

        consumer._buffer.add(1, "s", '{"a": 1}')
        consumer._flush_all("test")

        mock_kafka_consumer.commit.assert_called_once_with(asynchronous=False)

    @patch("products.data_warehouse.backend.webhook_consumer.consumer.WebhookParquetWriter")
    def test_flush_sends_failed_buffer_to_dlq(self, mock_writer_cls):
        mock_writer = MagicMock()
        mock_writer.write.side_effect = ConnectionError("S3 unreachable")
        mock_writer_cls.return_value = mock_writer

        consumer = _make_consumer(config=_make_config(max_retries=1, retry_backoff_seconds=0.0))
        consumer._consumer = MagicMock()
        consumer._dlq_producer = MagicMock()

        consumer._buffer.add(1, "schema-a", '{"a": 1}')
        consumer._buffer.add(1, "schema-a", '{"a": 2}')

        consumer._flush_all("test")

        # 2 messages should be sent to DLQ
        assert consumer._dlq_producer.produce.call_count == 2
        # Offsets should still be committed
        consumer._consumer.commit.assert_called_once()

    @patch("products.data_warehouse.backend.webhook_consumer.consumer.WebhookParquetWriter")
    def test_flush_retries_transient_s3_errors(self, mock_writer_cls):
        mock_writer = MagicMock()
        mock_writer.write.side_effect = [
            ConnectionError("transient"),
            "s3://bucket/path.parquet",
        ]
        mock_writer_cls.return_value = mock_writer

        consumer = _make_consumer(config=_make_config(max_retries=2, retry_backoff_seconds=0.0))
        consumer._consumer = MagicMock()

        consumer._buffer.add(1, "s", '{"a": 1}')
        consumer._flush_all("test")

        assert mock_writer.write.call_count == 2
        consumer._consumer.commit.assert_called_once()

    @patch("products.data_warehouse.backend.webhook_consumer.consumer.WebhookParquetWriter")
    def test_flush_non_transient_error_goes_to_dlq_immediately(self, mock_writer_cls):
        mock_writer = MagicMock()
        mock_writer.write.side_effect = ValueError("bad data")
        mock_writer_cls.return_value = mock_writer

        consumer = _make_consumer(config=_make_config(max_retries=3, retry_backoff_seconds=0.0))
        consumer._consumer = MagicMock()
        consumer._dlq_producer = MagicMock()

        consumer._buffer.add(1, "s", '{"a": 1}')
        consumer._flush_all("test")

        # Non-transient error should not retry
        assert mock_writer.write.call_count == 1
        assert consumer._dlq_producer.produce.call_count == 1

    @patch("products.data_warehouse.backend.webhook_consumer.consumer.WebhookParquetWriter")
    def test_flush_clears_buffer(self, mock_writer_cls):
        mock_writer = MagicMock()
        mock_writer.write.return_value = "s3://bucket/path.parquet"
        mock_writer_cls.return_value = mock_writer

        consumer = _make_consumer()
        consumer._consumer = MagicMock()

        consumer._buffer.add(1, "s", '{"a": 1}')
        consumer._flush_all("test")

        assert consumer._buffer.total_messages == 0
        assert consumer._buffer.total_size_bytes == 0

    def test_flush_noop_when_empty(self):
        consumer = _make_consumer()
        consumer._consumer = MagicMock()

        consumer._flush_all("test")

        consumer._consumer.commit.assert_not_called()


class TestWebhookS3SinkCallbacks:
    @patch("products.data_warehouse.backend.webhook_consumer.consumer.WebhookParquetWriter")
    def test_on_revoke_flushes_buffer(self, mock_writer_cls):
        mock_writer = MagicMock()
        mock_writer.write.return_value = "s3://bucket/path.parquet"
        mock_writer_cls.return_value = mock_writer

        consumer = _make_consumer()
        consumer._consumer = MagicMock()

        consumer._buffer.add(1, "s", '{"a": 1}')

        partition = MagicMock()
        partition.topic = "test-topic"
        partition.partition = 0
        partition.offset = 42
        consumer._on_revoke(consumer._consumer, [partition])

        # Buffer should have been flushed
        assert consumer._buffer.total_messages == 0
        mock_writer.write.assert_called_once()

    def test_on_revoke_noop_when_buffer_empty(self):
        consumer = _make_consumer()
        consumer._consumer = MagicMock()

        partition = MagicMock()
        partition.topic = "test-topic"
        partition.partition = 0
        partition.offset = 42
        consumer._on_revoke(consumer._consumer, [partition])

        consumer._consumer.commit.assert_not_called()


class TestWebhookS3SinkRunLoop:
    @patch("products.data_warehouse.backend.webhook_consumer.consumer.WebhookParquetWriter")
    @patch("products.data_warehouse.backend.webhook_consumer.consumer.ConfluentConsumer")
    def test_run_processes_messages_and_flushes(self, mock_consumer_cls, mock_writer_cls):
        mock_writer = MagicMock()
        mock_writer.write.return_value = "s3://bucket/path.parquet"
        mock_writer_cls.return_value = mock_writer

        mock_kafka = MagicMock()
        mock_consumer_cls.return_value = mock_kafka

        msg = _make_kafka_message({"team_id": 1, "schema_id": "s", "payload": '{"data": "test"}'})
        call_count = 0

        def consume_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [msg]
            return []

        mock_kafka.consume.side_effect = consume_side_effect

        config = _make_config(flush_interval_seconds=0.0, poll_timeout_seconds=0.01)
        consumer = WebhookS3Sink(
            config=config,
            kafka_hosts=["localhost:9092"],
            kafka_security_protocol="PLAINTEXT",
        )

        # Stop after 3 iterations
        iteration = 0

        def stop_after_iterations():
            nonlocal iteration
            iteration += 1
            if iteration >= 3:
                consumer._shutdown_requested = True

        consumer.run(health_reporter=stop_after_iterations)

        mock_writer.write.assert_called()
        mock_kafka.commit.assert_called()

    @patch("products.data_warehouse.backend.webhook_consumer.consumer.WebhookParquetWriter")
    @patch("products.data_warehouse.backend.webhook_consumer.consumer.ConfluentConsumer")
    def test_run_flushes_on_shutdown(self, mock_consumer_cls, mock_writer_cls):
        mock_writer = MagicMock()
        mock_writer.write.return_value = "s3://bucket/path.parquet"
        mock_writer_cls.return_value = mock_writer

        mock_kafka = MagicMock()
        mock_consumer_cls.return_value = mock_kafka

        msg = _make_kafka_message({"team_id": 1, "schema_id": "s", "payload": '{"data": "test"}'})
        call_count = 0

        def consume_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [msg]
            return []

        mock_kafka.consume.side_effect = consume_side_effect

        # High flush interval so it won't trigger during the loop
        config = _make_config(flush_interval_seconds=9999, poll_timeout_seconds=0.01)
        consumer = WebhookS3Sink(
            config=config,
            kafka_hosts=["localhost:9092"],
            kafka_security_protocol="PLAINTEXT",
        )

        iteration = 0

        def stop_after_iterations():
            nonlocal iteration
            iteration += 1
            if iteration >= 3:
                consumer._shutdown_requested = True

        consumer.run(health_reporter=stop_after_iterations)

        # Should still flush on shutdown even though interval wasn't reached
        mock_writer.write.assert_called_once()
        mock_kafka.commit.assert_called()

    @patch("products.data_warehouse.backend.webhook_consumer.consumer.ConfluentConsumer")
    def test_run_skips_kafka_errors(self, mock_consumer_cls):
        mock_kafka = MagicMock()
        mock_consumer_cls.return_value = mock_kafka

        error = MagicMock()
        error.code.return_value = 999
        error_msg = _make_kafka_message(error=error)

        call_count = 0

        def consume_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [error_msg]
            return []

        mock_kafka.consume.side_effect = consume_side_effect

        consumer = _make_consumer(config=_make_config(poll_timeout_seconds=0.01))

        iteration = 0

        def stop_after_iterations():
            nonlocal iteration
            iteration += 1
            if iteration >= 2:
                consumer._shutdown_requested = True

        consumer.run(health_reporter=stop_after_iterations)

        assert consumer._buffer.total_messages == 0

    @patch("products.data_warehouse.backend.webhook_consumer.consumer.ConfluentConsumer")
    def test_run_closes_consumer_on_cleanup(self, mock_consumer_cls):
        mock_kafka = MagicMock()
        mock_consumer_cls.return_value = mock_kafka
        mock_kafka.consume.return_value = []

        consumer = _make_consumer(config=_make_config(poll_timeout_seconds=0.01))
        consumer._shutdown_requested = True

        consumer.run()

        mock_kafka.close.assert_called_once()


class TestWebhookS3SinkDLQ:
    def test_dlq_message_format(self):
        consumer = _make_consumer()
        consumer._dlq_producer = MagicMock()

        raw = json.dumps({"bad": "data"}).encode("utf-8")
        error = ValueError("test error")

        consumer._send_to_dlq(raw, error)

        produce_call = consumer._dlq_producer.produce.call_args
        dlq_data = produce_call.kwargs["data"]

        assert dlq_data["error_type"] == "ValueError"
        assert dlq_data["error_message"] == "test error"
        assert dlq_data["input_topic"] == "test-topic"
        assert dlq_data["consumer_group"] == "test-group"
        assert "original_message" in dlq_data
        assert "failed_at" in dlq_data

    def test_dlq_handles_binary_messages(self):
        consumer = _make_consumer()
        consumer._dlq_producer = MagicMock()

        consumer._send_to_dlq(b"\x80\x81", ValueError("bad bytes"))

        produce_call = consumer._dlq_producer.produce.call_args
        dlq_data = produce_call.kwargs["data"]
        assert "original_message" in dlq_data
