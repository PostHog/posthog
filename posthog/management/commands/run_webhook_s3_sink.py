from django.core.management.base import BaseCommand

import structlog

from posthog.kafka_client.topics import KAFKA_WAREHOUSE_SOURCE_WEBHOOKS, KAFKA_WAREHOUSE_SOURCE_WEBHOOKS_DLQ
from posthog.temporal.data_imports.pipelines.pipeline_v3.load.health import HealthState, start_health_server

from products.data_warehouse.backend.webhook_consumer.config import WebhookConsumerConfig
from products.data_warehouse.backend.webhook_consumer.consumer import WebhookS3Sink

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Run the webhook S3 sink (consumes from Kafka, writes parquet to S3)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--consumer-group",
            type=str,
            required=True,
            help="Kafka consumer group ID",
        )
        parser.add_argument(
            "--health-port",
            type=int,
            default=8081,
            help="Port for the health check HTTP server (default: 8081)",
        )
        parser.add_argument(
            "--flush-interval",
            type=float,
            default=60.0,
            help="Flush interval in seconds (default: 60.0)",
        )
        parser.add_argument(
            "--max-batch-messages",
            type=int,
            default=10_000,
            help="Max total messages before flush (default: 10000)",
        )
        parser.add_argument(
            "--max-buffer-size-mb",
            type=int,
            default=2048,
            help="Max total buffer size in MB before flush (default: 2048)",
        )
        parser.add_argument(
            "--input-topic",
            type=str,
            default=KAFKA_WAREHOUSE_SOURCE_WEBHOOKS,
            help="Kafka topic to consume messages from",
        )
        parser.add_argument(
            "--dlq-topic",
            type=str,
            default=KAFKA_WAREHOUSE_SOURCE_WEBHOOKS_DLQ,
            help="Kafka topic for dead-letter queue messages",
        )
        parser.add_argument(
            "--health-timeout",
            type=float,
            default=120.0,
            help="Health check timeout in seconds (default: 120.0)",
        )

    def handle(self, *args, **options):
        health_port = options["health_port"]
        health_timeout = options["health_timeout"]

        logger.info(
            "webhook_s3_sink_starting",
            health_port=health_port,
            input_topic=options["input_topic"],
            consumer_group=options["consumer_group"],
            flush_interval=options["flush_interval"],
            max_batch_messages=options["max_batch_messages"],
            max_buffer_size_mb=options["max_buffer_size_mb"],
            dlq_topic=options["dlq_topic"],
        )

        health_state = HealthState(timeout_seconds=health_timeout)
        start_health_server(port=health_port, health_state=health_state)

        config = WebhookConsumerConfig(
            input_topic=options["input_topic"],
            consumer_group=options["consumer_group"],
            dlq_topic=options["dlq_topic"],
            flush_interval_seconds=options["flush_interval"],
            max_batch_messages=options["max_batch_messages"],
            max_buffer_size_bytes=options["max_buffer_size_mb"] * 1024 * 1024,
            health_port=health_port,
            health_timeout_seconds=health_timeout,
        )

        consumer = WebhookS3Sink(config=config)
        consumer.run(health_reporter=health_state.report_healthy)
