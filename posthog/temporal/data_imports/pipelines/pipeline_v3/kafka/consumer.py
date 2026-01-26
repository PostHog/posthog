import json
import time
import signal
from collections.abc import Callable
from typing import Any, Optional

from django.conf import settings
from django.db import OperationalError

import structlog
from kafka import KafkaConsumer

from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.client import _KafkaSecurityProtocol, _sasl_params
from posthog.temporal.data_imports.pipelines.pipeline_v3.load.config import ConsumerConfig

logger = structlog.get_logger(__name__)

TRANSIENT_ERRORS = (
    OperationalError,  # Database connection issues
    ConnectionError,
    TimeoutError,
    OSError,
)


class KafkaConsumerService:
    """A continuously running Kafka consumer service with graceful shutdown support:
    - Runs an infinite loop polling for messages
    - Supports graceful shutdown via SIGTERM/SIGINT
    - Manually commits offsets after successful processing
    - Reports health status each loop iteration
    """

    def __init__(
        self,
        config: ConsumerConfig,
        process_message: Callable[[Any], None],
        kafka_hosts: Optional[list[str]] = None,
        kafka_security_protocol: Optional[str] = None,
    ):
        self._config = config
        self._process_message = process_message
        self._kafka_hosts = kafka_hosts or settings.WAREHOUSE_PIPELINES_KAFKA_HOSTS
        self._kafka_security_protocol = kafka_security_protocol or settings.WAREHOUSE_PIPELINES_KAFKA_SECURITY_PROTOCOL
        self._shutdown_requested = False
        self._consumer: Optional[KafkaConsumer] = None

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""

        def handle_signal(signum: int, frame: Any) -> None:
            signal_name = signal.Signals(signum).name
            logger.info("shutdown_signal_received", signal=signal_name)
            self._shutdown_requested = True

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, handle_signal)
            except ValueError:
                logger.warning("signal_registration_failed", signal=sig)

    def _create_consumer(self) -> KafkaConsumer:
        consumer = KafkaConsumer(
            self._config.input_topic,
            bootstrap_servers=self._kafka_hosts,
            group_id=self._config.consumer_group,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            security_protocol=self._kafka_security_protocol or _KafkaSecurityProtocol.PLAINTEXT,
            **_sasl_params(),
        )
        return consumer

    def run(self, health_reporter: Optional[Callable[[], None]] = None) -> None:
        self._setup_signal_handlers()

        logger.info(
            "consumer_starting",
            input_topic=self._config.input_topic,
            consumer_group=self._config.consumer_group,
            batch_size=self._config.batch_size,
            batch_timeout_seconds=self._config.batch_timeout_seconds,
            kafka_hosts=self._kafka_hosts,
        )

        try:
            self._consumer = self._create_consumer()

            logger.info("consumer_started")

            while not self._shutdown_requested:
                if health_reporter:
                    health_reporter()

                timeout_ms = int(self._config.batch_timeout_seconds * 1000)
                records = self._consumer.poll(
                    timeout_ms=timeout_ms,
                    max_records=self._config.batch_size,
                )

                if not records:
                    continue

                messages: list[Any] = []
                for _topic_partition, partition_records in records.items():
                    messages.extend(partition_records)

                if not messages:
                    continue

                logger.debug("batch_received", message_count=len(messages))

                self._process_batch_with_retry(messages)

        except Exception as e:
            logger.exception("consumer_error")
            capture_exception(e)
            raise
        finally:
            self._cleanup()

    def _process_batch_with_retry(self, messages: list[Any]) -> None:
        """Process a batch of messages with retry logic for transient errors."""
        assert self._consumer is not None

        for attempt in range(self._config.max_retries):
            try:
                for message in messages:
                    self._process_message(message)
                self._consumer.commit()
                logger.debug("batch_committed", message_count=len(messages))
                return
            except TRANSIENT_ERRORS as e:
                if attempt == self._config.max_retries - 1:
                    logger.exception(
                        "batch_processing_failed_after_retries",
                        attempts=self._config.max_retries,
                        error_type=type(e).__name__,
                    )
                    capture_exception(e)
                    raise
                backoff = self._config.retry_backoff_seconds * (2**attempt)
                logger.warning(
                    "transient_error_retrying",
                    attempt=attempt + 1,
                    max_retries=self._config.max_retries,
                    backoff_seconds=backoff,
                    error_type=type(e).__name__,
                )
                time.sleep(backoff)
            except Exception as e:
                logger.exception(
                    "batch_processing_failed"
                )  # TODO: log these errors also on the DB, use the debug column or something else to make sure we don't retry them for ever, probably we need to have a DLQ for them and monitor it
                capture_exception(e)
                raise

    def _cleanup(self) -> None:
        logger.info("consumer_shutting_down")

        if self._consumer:
            try:
                self._consumer.close()
                logger.info("consumer_closed")
            except Exception as e:
                logger.exception("consumer_close_failed")
                capture_exception(e)

        logger.info("consumer_shutdown_complete")
