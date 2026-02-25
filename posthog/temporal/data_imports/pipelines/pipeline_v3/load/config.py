from dataclasses import dataclass


@dataclass
class ConsumerConfig:
    """Configuration for the Kafka consumer service."""

    input_topic: str
    consumer_group: str
    dlq_topic: str
    batch_size: int = 1000
    batch_timeout_seconds: float = 5.0
    health_port: int = 8080
    health_timeout_seconds: float = 60.0
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0
