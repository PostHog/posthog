from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.pipelines.pipeline_v3.kafka.consumer import (
    KafkaConsumerService,
    _extract_message_key,
)
from posthog.temporal.data_imports.pipelines.pipeline_v3.load.config import ConsumerConfig
from posthog.temporal.data_imports.pipelines.pipeline_v3.load.retry_tracker import RetryInfo


def _make_config(**kwargs) -> ConsumerConfig:
    defaults: dict[str, Any] = {
        "input_topic": "test-topic",
        "consumer_group": "test-group",
        "dlq_topic": "test-dlq",
    }
    defaults.update(kwargs)
    return ConsumerConfig(**defaults)


def _make_service(**kwargs) -> KafkaConsumerService:
    defaults: dict = {
        "config": _make_config(),
        "process_message": MagicMock(),
        "kafka_hosts": ["localhost:9092"],
        "kafka_security_protocol": "PLAINTEXT",
    }
    defaults.update(kwargs)
    return KafkaConsumerService(**defaults)


class TestKafkaConsumerServiceConfig:
    def test_consumer_uses_latest_offset_reset(self):
        service = _make_service()

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.kafka.consumer.ConfluentConsumer"
        ) as mock_consumer_cls:
            mock_consumer_cls.return_value = MagicMock()
            service._create_consumer()

            config = mock_consumer_cls.call_args[0][0]
            assert config["auto.offset.reset"] == "latest"

    def test_subscribe_registers_callbacks(self):
        service = _make_service()

        with patch(
            "posthog.temporal.data_imports.pipelines.pipeline_v3.kafka.consumer.ConfluentConsumer"
        ) as mock_consumer_cls:
            mock_instance = MagicMock()
            mock_consumer_cls.return_value = mock_instance
            service._create_consumer()

            mock_instance.subscribe.assert_called_once_with(
                ["test-topic"],
                on_assign=service._on_assign,
                on_revoke=service._on_revoke,
            )


class TestKafkaConsumerServiceCallbacks:
    @parameterized.expand(
        [
            ("single_partition", [("test-topic", 0, 42)]),
            ("multiple_partitions", [("test-topic", 0, 10), ("test-topic", 1, 20)]),
        ]
    )
    def test_on_assign_logs_partition_info(self, _name, partition_data):
        service = _make_service()
        partitions = []
        for topic, partition, offset in partition_data:
            p = MagicMock()
            p.topic = topic
            p.partition = partition
            p.offset = offset
            partitions.append(p)

        with patch("posthog.temporal.data_imports.pipelines.pipeline_v3.kafka.consumer.logger") as mock_logger:
            service._on_assign(MagicMock(), partitions)

            assert mock_logger.info.call_count == len(partition_data)
            for topic, partition, offset in partition_data:
                mock_logger.info.assert_any_call(
                    "partition_assigned",
                    topic=topic,
                    partition=partition,
                    offset=offset,
                )

    @parameterized.expand(
        [
            ("single_partition", [("test-topic", 0, 42)]),
            ("multiple_partitions", [("test-topic", 0, 10), ("test-topic", 1, 20)]),
        ]
    )
    def test_on_revoke_logs_partition_info(self, _name, partition_data):
        service = _make_service()
        partitions = []
        for topic, partition, offset in partition_data:
            p = MagicMock()
            p.topic = topic
            p.partition = partition
            p.offset = offset
            partitions.append(p)

        with patch("posthog.temporal.data_imports.pipelines.pipeline_v3.kafka.consumer.logger") as mock_logger:
            mock_consumer = MagicMock()
            service._on_revoke(mock_consumer, partitions)

            assert mock_logger.info.call_count == len(partition_data)
            for topic, partition, offset in partition_data:
                mock_logger.info.assert_any_call(
                    "partition_revoked",
                    topic=topic,
                    partition=partition,
                    offset=offset,
                )
            mock_consumer.commit.assert_called_once_with(asynchronous=False)

    def test_on_revoke_logs_warning_on_commit_failure(self):
        service = _make_service()
        mock_consumer = MagicMock()
        mock_consumer.commit.side_effect = Exception("commit failed")

        with patch("posthog.temporal.data_imports.pipelines.pipeline_v3.kafka.consumer.logger") as mock_logger:
            service._on_revoke(mock_consumer, [])

            mock_logger.warning.assert_called_once_with("failed_to_commit_on_revoke", error="commit failed")

    def test_on_revoke_logs_debug_on_no_offset(self):
        from confluent_kafka import KafkaError, KafkaException

        service = _make_service()
        mock_consumer = MagicMock()
        kafka_error = KafkaError(KafkaError._NO_OFFSET)  # type: ignore[attr-defined]
        mock_consumer.commit.side_effect = KafkaException(kafka_error)

        with patch("posthog.temporal.data_imports.pipelines.pipeline_v3.kafka.consumer.logger") as mock_logger:
            service._on_revoke(mock_consumer, [])

            mock_logger.debug.assert_called_once_with("no_offsets_to_commit_on_revoke")
            mock_logger.warning.assert_not_called()

    def test_on_revoke_logs_warning_on_kafka_exception(self):
        from confluent_kafka import KafkaError, KafkaException

        service = _make_service()
        mock_consumer = MagicMock()
        kafka_error = KafkaError(KafkaError._FAIL)  # type: ignore[attr-defined]
        mock_consumer.commit.side_effect = KafkaException(kafka_error)

        with patch("posthog.temporal.data_imports.pipelines.pipeline_v3.kafka.consumer.logger") as mock_logger:
            service._on_revoke(mock_consumer, [])

            mock_logger.warning.assert_called_once()


def _make_message(**overrides) -> dict:
    defaults: dict[str, Any] = {
        "team_id": 1,
        "schema_id": "schema-1",
        "run_uuid": "run-1",
        "batch_index": 0,
        "job_id": "job-1",
        "source_id": "source-1",
        "resource_name": "test_resource",
        "s3_path": "s3://bucket/path",
        "row_count": 100,
        "byte_size": 1024,
        "is_final_batch": False,
        "total_batches": None,
        "total_rows": None,
        "sync_type": "full_refresh",
        "data_folder": None,
        "schema_path": None,
        "primary_keys": None,
    }
    defaults.update(overrides)
    return defaults


RETRY_TRACKER_PATH = "posthog.temporal.data_imports.pipelines.pipeline_v3.kafka.consumer"


class TestExtractMessageKey:
    def test_extracts_key_from_valid_message(self):
        msg = _make_message()
        assert _extract_message_key(msg) == (1, "schema-1", "run-1", 0)

    @parameterized.expand(
        [
            ("missing_team_id", {"schema_id": "s", "run_uuid": "r", "batch_index": 0}),
            ("missing_schema_id", {"team_id": 1, "run_uuid": "r", "batch_index": 0}),
            ("missing_run_uuid", {"team_id": 1, "schema_id": "s", "batch_index": 0}),
            ("missing_batch_index", {"team_id": 1, "schema_id": "s", "run_uuid": "r"}),
            ("empty_dict", {}),
        ]
    )
    def test_returns_none_for_incomplete_message(self, _name, msg):
        assert _extract_message_key(msg) is None


class TestProcessBatchPersistentRetry:
    def _setup_service(self, process_message: Any = None) -> KafkaConsumerService:
        service = _make_service(process_message=process_message or MagicMock())
        service._consumer = MagicMock()
        return service

    @patch(f"{RETRY_TRACKER_PATH}.clear_retry_info")
    @patch(f"{RETRY_TRACKER_PATH}.increment_retry_count", return_value=RetryInfo(count=1))
    @patch(f"{RETRY_TRACKER_PATH}.get_retry_info", return_value=RetryInfo(count=0))
    def test_successful_processing_clears_retry_info(self, mock_get, mock_inc, mock_clear):
        service = self._setup_service()
        msg = _make_message()

        service._process_batch_with_retry([msg])

        mock_inc.assert_called_once_with(1, "schema-1", "run-1", 0)
        mock_clear.assert_called_once_with(1, "schema-1", "run-1", 0)
        cast(MagicMock, service._consumer).commit.assert_called_once()

    @patch(f"{RETRY_TRACKER_PATH}.update_retry_error_type")
    @patch(f"{RETRY_TRACKER_PATH}.increment_retry_count", return_value=RetryInfo(count=1))
    @patch(f"{RETRY_TRACKER_PATH}.get_retry_info", return_value=RetryInfo(count=0))
    def test_non_exhausted_failure_reraises(self, mock_get, mock_inc, mock_update):
        process_fn = MagicMock(side_effect=ValueError("bad data"))
        service = self._setup_service(process_message=process_fn)
        msg = _make_message()

        with pytest.raises(ValueError, match="bad data"):
            service._process_batch_with_retry([msg])

        mock_update.assert_called_once_with(
            1, "schema-1", "run-1", 0, error_type="non_transient", last_error="bad data"
        )
        cast(MagicMock, service._consumer).commit.assert_not_called()

    @patch(f"{RETRY_TRACKER_PATH}.clear_retry_info")
    @patch(f"{RETRY_TRACKER_PATH}.update_retry_error_type")
    @patch(f"{RETRY_TRACKER_PATH}.increment_retry_count", return_value=RetryInfo(count=4, error_type="non_transient"))
    @patch(f"{RETRY_TRACKER_PATH}.get_retry_info", return_value=RetryInfo(count=3, error_type="non_transient"))
    def test_exhausted_after_attempt_sends_to_dlq(self, mock_get, mock_inc, mock_update, mock_clear):
        process_fn = MagicMock(side_effect=ValueError("bad data"))
        service = self._setup_service(process_message=process_fn)
        msg = _make_message()

        with (
            patch.object(service, "_send_to_dlq") as mock_dlq,
            patch.object(service, "_mark_job_failed_from_message") as mock_fail,
        ):
            service._process_batch_with_retry([msg])

            mock_dlq.assert_called_once()
            mock_fail.assert_called_once()
            mock_clear.assert_called_once_with(1, "schema-1", "run-1", 0)
            cast(MagicMock, service._consumer).commit.assert_called_once()

    @patch(f"{RETRY_TRACKER_PATH}.clear_retry_info")
    @patch(f"{RETRY_TRACKER_PATH}.increment_retry_count")
    @patch(
        f"{RETRY_TRACKER_PATH}.get_retry_info",
        return_value=RetryInfo(count=4, error_type="non_transient", last_error="previous error"),
    )
    def test_already_exhausted_skips_processing(self, mock_get, mock_inc, mock_clear):
        process_fn = MagicMock()
        service = self._setup_service(process_message=process_fn)
        msg = _make_message()

        with (
            patch.object(service, "_send_to_dlq") as mock_dlq,
            patch.object(service, "_mark_job_failed_from_message") as mock_fail,
        ):
            service._process_batch_with_retry([msg])

            process_fn.assert_not_called()
            mock_inc.assert_not_called()
            mock_dlq.assert_called_once()
            mock_fail.assert_called_once()
            mock_clear.assert_called_once()
            cast(MagicMock, service._consumer).commit.assert_called_once()

    @patch(f"{RETRY_TRACKER_PATH}.clear_retry_info")
    @patch(f"{RETRY_TRACKER_PATH}.increment_retry_count", return_value=RetryInfo(count=1))
    @patch(f"{RETRY_TRACKER_PATH}.get_retry_info", return_value=RetryInfo(count=0))
    def test_pre_increments_before_processing(self, mock_get, mock_inc, mock_clear):
        call_order: list[str] = []

        def track_process(msg):
            call_order.append("process")

        def _increment_side_effect(*a: Any) -> RetryInfo:
            call_order.append("increment")
            return RetryInfo(count=1)

        mock_inc.side_effect = _increment_side_effect

        service = self._setup_service(process_message=track_process)
        msg = _make_message()

        service._process_batch_with_retry([msg])

        assert call_order == ["increment", "process"]

    @patch(f"{RETRY_TRACKER_PATH}.update_retry_error_type")
    @patch(f"{RETRY_TRACKER_PATH}.increment_retry_count", return_value=RetryInfo(count=1))
    @patch(f"{RETRY_TRACKER_PATH}.get_retry_info", return_value=RetryInfo(count=0))
    def test_transient_error_classified_correctly(self, mock_get, mock_inc, mock_update):
        process_fn = MagicMock(side_effect=ConnectionError("reset"))
        service = self._setup_service(process_message=process_fn)
        msg = _make_message()

        with pytest.raises(ConnectionError):
            service._process_batch_with_retry([msg])

        mock_update.assert_called_once_with(1, "schema-1", "run-1", 0, error_type="transient", last_error="reset")

    @patch(f"{RETRY_TRACKER_PATH}.clear_retry_info")
    @patch(f"{RETRY_TRACKER_PATH}.increment_retry_count")
    @patch(f"{RETRY_TRACKER_PATH}.get_retry_info")
    def test_multiple_messages_first_fails_second_not_attempted(self, mock_get, mock_inc, mock_clear):
        call_count = 0

        def process_fn(msg):
            nonlocal call_count
            call_count += 1
            if msg["batch_index"] == 0:
                raise ValueError("bad")

        mock_get.return_value = RetryInfo(count=0)
        mock_inc.return_value = RetryInfo(count=1)

        service = self._setup_service(process_message=process_fn)
        msg1 = _make_message(batch_index=0)
        msg2 = _make_message(batch_index=1)

        with pytest.raises(ValueError):
            service._process_batch_with_retry([msg1, msg2])

        # Only the first message was attempted
        assert call_count == 1
        cast(MagicMock, service._consumer).commit.assert_not_called()
