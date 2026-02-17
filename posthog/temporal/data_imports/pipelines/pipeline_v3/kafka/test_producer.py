import pytest
from unittest.mock import MagicMock, patch

from confluent_kafka import KafkaError, KafkaException
from parameterized import parameterized

from posthog.kafka_client.client import ProduceResult
from posthog.temporal.data_imports.pipelines.pipeline_v3.kafka.producer import KafkaBatchProducer
from posthog.temporal.data_imports.pipelines.pipeline_v3.s3 import BatchWriteResult


def _make_producer(**kwargs) -> KafkaBatchProducer:
    defaults = {
        "team_id": 1,
        "job_id": "job-1",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "resource_name": "test_resource",
        "sync_type": "full_refresh",
        "run_uuid": "run-1",
        "logger": MagicMock(),
    }
    defaults.update(kwargs)
    with patch(
        "posthog.temporal.data_imports.pipelines.pipeline_v3.kafka.producer.get_warpstream_kafka_producer"
    ) as mock_get:
        mock_get.return_value = MagicMock()
        return KafkaBatchProducer(**defaults)


def _make_batch_result(batch_index: int = 0) -> BatchWriteResult:
    return BatchWriteResult(
        batch_index=batch_index,
        s3_path="s3://bucket/path",
        row_count=100,
        byte_size=1024,
        timestamp_ns=0,
    )


def _successful_future() -> MagicMock:
    future = MagicMock(spec=ProduceResult)
    future.get.return_value = None
    return future


def _failed_future(error_msg: str = "delivery failed") -> MagicMock:
    future = MagicMock(spec=ProduceResult)
    future.get.side_effect = KafkaException(KafkaError._MSG_TIMED_OUT, error_msg)
    return future


class TestKafkaBatchProducerFlush:
    def test_flush_returns_count_on_success(self):
        producer = _make_producer()
        producer._pending_futures = [_successful_future(), _successful_future()]

        result = producer.flush()

        assert result == 2
        assert producer._pending_futures == []

    def test_flush_returns_zero_when_no_pending(self):
        producer = _make_producer()

        result = producer.flush()

        assert result == 0

    def test_flush_raises_on_single_error(self):
        producer = _make_producer()
        producer._pending_futures = [_failed_future()]

        with pytest.raises(Exception, match="Failed to deliver 1/1 Kafka messages"):
            producer.flush()

        assert producer._pending_futures == []

    def test_flush_raises_on_partial_errors(self):
        producer = _make_producer()
        producer._pending_futures = [
            _successful_future(),
            _failed_future("first error"),
            _successful_future(),
            _failed_future("second error"),
        ]

        with pytest.raises(Exception, match="Failed to deliver 2/4 Kafka messages"):
            producer.flush()

        assert producer._pending_futures == []

    @parameterized.expand(
        [
            ("all_fail", [True, True, True], 3, 3),
            ("one_fails", [False, True, False], 1, 3),
        ]
    )
    def test_flush_error_counts(self, _name, failure_flags, expected_errors, expected_total):
        producer = _make_producer()
        producer._pending_futures = [
            _failed_future() if should_fail else _successful_future() for should_fail in failure_flags
        ]

        with pytest.raises(Exception, match=f"Failed to deliver {expected_errors}/{expected_total} Kafka messages"):
            producer.flush()

    def test_flush_clears_futures_even_on_error(self):
        producer = _make_producer()
        producer._pending_futures = [_failed_future()]

        with pytest.raises(Exception):
            producer.flush()

        assert producer._pending_futures == []

    def test_flush_passes_timeout_to_underlying_producer(self):
        producer = _make_producer()
        producer._pending_futures = [_successful_future()]

        producer.flush(timeout=5.0)

        producer._producer.flush.assert_called_once_with(timeout=5.0)
