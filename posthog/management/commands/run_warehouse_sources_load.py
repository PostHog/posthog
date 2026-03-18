from django.core.management.base import BaseCommand

import structlog

from posthog.kafka_client.topics import KAFKA_WAREHOUSE_SOURCES_JOBS, KAFKA_WAREHOUSE_SOURCES_JOBS_DLQ
from posthog.temporal.data_imports.pipelines.pipeline_v3.kafka import KafkaConsumerService
from posthog.temporal.data_imports.pipelines.pipeline_v3.load import (
    ConsumerConfig,
    HealthState,
    process_message,
    start_health_server,
)

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Run the warehouse sources load Kafka consumer service"

    def add_arguments(self, parser):
        parser.add_argument(
            "--health-port",
            type=int,
            default=8080,
            help="Port for the health check HTTP server (default: 8080)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Maximum number of messages to process per batch (default: 1000)",
        )
        parser.add_argument(
            "--batch-timeout",
            type=float,
            default=5.0,
            help="Timeout in seconds for polling a batch (default: 5.0)",
        )
        parser.add_argument(
            "--input-topic",
            type=str,
            default=KAFKA_WAREHOUSE_SOURCES_JOBS,
            help="Kafka topic to consume messages from",
        )
        parser.add_argument(
            "--consumer-group",
            type=str,
            required=True,
            help="Kafka consumer group ID",
        )
        parser.add_argument(
            "--health-timeout",
            type=float,
            default=60.0,
            help="Health check timeout in seconds (default: 60.0)",
        )
        parser.add_argument(
            "--dlq-topic",
            type=str,
            default=KAFKA_WAREHOUSE_SOURCES_JOBS_DLQ,
            help="Kafka topic for dead-letter queue messages",
        )

    def handle(self, *args, **options):
        health_port = options["health_port"]
        batch_size = options["batch_size"]
        batch_timeout = options["batch_timeout"]
        input_topic = options["input_topic"]
        consumer_group = options["consumer_group"]
        health_timeout = options["health_timeout"]
        dlq_topic = options["dlq_topic"]

        logger.info(
            "warehouse_sources_load_starting",
            health_port=health_port,
            batch_size=batch_size,
            batch_timeout=batch_timeout,
            input_topic=input_topic,
            consumer_group=consumer_group,
            health_timeout=health_timeout,
            dlq_topic=dlq_topic,
        )

        health_state = HealthState(timeout_seconds=health_timeout)

        start_health_server(port=health_port, health_state=health_state)

        config = ConsumerConfig(
            input_topic=input_topic,
            consumer_group=consumer_group,
            dlq_topic=dlq_topic,
            batch_size=batch_size,
            batch_timeout_seconds=batch_timeout,
            health_port=health_port,
            health_timeout_seconds=health_timeout,
        )

        consumer = KafkaConsumerService(
            config=config,
            process_message=process_message,
        )

        consumer.run(health_reporter=health_state.report_healthy)
