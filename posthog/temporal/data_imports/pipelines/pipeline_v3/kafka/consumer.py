import json
import time
import signal
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Optional

from django.conf import settings
from django.db import OperationalError

import structlog
from confluent_kafka import (
    Consumer as ConfluentConsumer,
    KafkaError,
)

from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.client import _KafkaProducer, _KafkaSecurityProtocol
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
    - Sends poison-pill messages to a dead-letter queue
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
        self._consumer: Optional[ConfluentConsumer] = None
        self._dlq_producer: Optional[_KafkaProducer] = None

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

    def _create_consumer(self) -> ConfluentConsumer:
        config: dict[str, str | int | float | bool | None] = {
            "bootstrap.servers": ",".join(self._kafka_hosts)
            if isinstance(self._kafka_hosts, list)
            else self._kafka_hosts,
            "group.id": self._config.consumer_group,
            "auto.offset.reset": "latest",
            "enable.auto.commit": False,
            "security.protocol": self._kafka_security_protocol or _KafkaSecurityProtocol.PLAINTEXT,
        }
        consumer = ConfluentConsumer(config)
        consumer.subscribe(
            [self._config.input_topic],
            on_assign=self._on_assign,
            on_revoke=self._on_revoke,
        )
        return consumer

    def _on_assign(self, consumer: ConfluentConsumer, partitions: list) -> None:
        for p in partitions:
            logger.info(
                "partition_assigned",
                topic=p.topic,
                partition=p.partition,
                offset=p.offset,
            )

    def _on_revoke(self, consumer: ConfluentConsumer, partitions: list) -> None:
        for p in partitions:
            logger.info(
                "partition_revoked",
                topic=p.topic,
                partition=p.partition,
                offset=p.offset,
            )

    def _get_dlq_producer(self) -> _KafkaProducer:
        if self._dlq_producer is None:
            self._dlq_producer = _KafkaProducer(
                kafka_hosts=self._kafka_hosts,
                kafka_security_protocol=self._kafka_security_protocol,
            )
        return self._dlq_producer

    def _send_to_dlq(self, message: Any, error: Exception) -> None:
        try:
            producer = self._get_dlq_producer()
            dlq_message = {
                "original_message": message,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "error_traceback": traceback.format_exception(error),
                "failed_at": datetime.now(tz=UTC).isoformat(),
                "input_topic": self._config.input_topic,
                "consumer_group": self._config.consumer_group,
            }
            producer.produce(
                topic=self._config.dlq_topic,
                data=dlq_message,
            )
            producer.flush(timeout=5.0)
            logger.warning(
                "message_sent_to_dlq",
                dlq_topic=self._config.dlq_topic,
                error_type=type(error).__name__,
                error_message=str(error),
            )
        except Exception as dlq_error:
            logger.exception(
                "dlq_send_failed",
                original_error_type=type(error).__name__,
            )
            capture_exception(dlq_error)

    def run(self, health_reporter: Optional[Callable[[], None]] = None) -> None:
        self._setup_signal_handlers()

        logger.info(
            "consumer_starting",
            input_topic=self._config.input_topic,
            consumer_group=self._config.consumer_group,
            batch_size=self._config.batch_size,
            batch_timeout_seconds=self._config.batch_timeout_seconds,
            kafka_hosts=self._kafka_hosts,
            dlq_topic=self._config.dlq_topic,
        )

        try:
            self._consumer = self._create_consumer()

            logger.info("consumer_started")

            while not self._shutdown_requested:
                if health_reporter:
                    health_reporter()

                raw_messages = self._consumer.consume(
                    num_messages=self._config.batch_size,
                    timeout=self._config.batch_timeout_seconds,
                )

                messages: list[Any] = []
                for msg in raw_messages:
                    err = msg.error()
                    if err is not None:
                        if err.code() == KafkaError._PARTITION_EOF:  # type: ignore[attr-defined]
                            continue
                        logger.error("kafka_message_error", error=err)
                        continue
                    raw = msg.value()
                    if raw is None:
                        continue
                    messages.append(json.loads(raw.decode("utf-8")))

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
        """Process a batch of messages with retry logic for transient errors.

        Non-transient errors on individual messages are sent to the DLQ so a
        single poison pill cannot block the partition.  Transient errors
        (infrastructure) still retry the whole batch and crash if exhausted
        — that is the right signal for the orchestrator to restart us.
        """
        assert self._consumer is not None

        dlq_indices: set[int] = set()

        for attempt in range(self._config.max_retries):
            try:
                for i, message in enumerate(messages):
                    if i in dlq_indices:
                        continue
                    try:
                        self._process_message(message)
                    except TRANSIENT_ERRORS:
                        raise
                    except Exception as e:
                        logger.exception(
                            "message_processing_failed",
                            error_type=type(e).__name__,
                        )
                        capture_exception(e)
                        try:
                            self._send_to_dlq(message, e)
                            dlq_indices.add(i)
                        except Exception:
                            raise e

                self._consumer.commit()
                processed = len(messages) - len(dlq_indices)
                logger.debug("batch_committed", message_count=processed, dlq_count=len(dlq_indices))
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
