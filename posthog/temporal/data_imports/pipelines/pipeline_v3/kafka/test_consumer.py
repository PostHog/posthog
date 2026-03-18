from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.pipelines.pipeline_v3.kafka.consumer import KafkaConsumerService
from posthog.temporal.data_imports.pipelines.pipeline_v3.load.config import ConsumerConfig


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

            mock_logger.warning.assert_called_once_with("failed_to_commit_on_revoke")
