from dataclasses import dataclass


@dataclass
class WebhookConsumerConfig:
    """Configuration for the webhook S3 Kafka consumer."""

    input_topic: str
    consumer_group: str
    dlq_topic: str
    flush_interval_seconds: float = 60.0
    max_batch_messages: int = 10_000
    max_buffer_size_bytes: int = 2 * 1024 * 1024 * 1024  # 2 GB
    poll_timeout_seconds: float = 1.0
    poll_batch_size: int = 500
    health_port: int = 8081
    health_timeout_seconds: float = 120.0
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0
