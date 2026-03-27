import json
import time
import signal
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any, Optional

from django.conf import settings

import structlog
from confluent_kafka import (
    Consumer as ConfluentConsumer,
    KafkaError,
)

from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.client import _KafkaProducer, _KafkaSecurityProtocol

from products.data_warehouse.backend.webhook_consumer.buffer import BatchBuffer, SchemaBuffer
from products.data_warehouse.backend.webhook_consumer.config import WebhookConsumerConfig
from products.data_warehouse.backend.webhook_consumer.metrics import (
    WEBHOOK_BUFFER_MESSAGE_COUNT,
    WEBHOOK_BUFFER_SIZE_BYTES,
    WEBHOOK_DLQ_MESSAGES_TOTAL,
    WEBHOOK_FLUSH_TOTAL,
    WEBHOOK_MESSAGES_BUFFERED_TOTAL,
    WEBHOOK_OFFSET_COMMITS_TOTAL,
    WEBHOOK_PARQUET_WRITE_DURATION_SECONDS,
    WEBHOOK_PARQUET_WRITES_TOTAL,
)
from products.data_warehouse.backend.webhook_consumer.writer import WebhookParquetWriter

logger = structlog.get_logger(__name__)

S3_TRANSIENT_ERRORS = (
    ConnectionError,
    TimeoutError,
    OSError,
)


class WebhookS3Sink:
    """Kafka consumer that batches webhook messages by schema_id and writes parquet files to S3."""

    def __init__(
        self,
        config: WebhookConsumerConfig,
        kafka_hosts: Optional[list[str]] = None,
        kafka_security_protocol: Optional[str] = None,
    ):
        self._config = config
        self._kafka_hosts = kafka_hosts or settings.WAREHOUSE_PIPELINES_KAFKA_HOSTS
        self._kafka_security_protocol = kafka_security_protocol or settings.WAREHOUSE_PIPELINES_KAFKA_SECURITY_PROTOCOL
        self._shutdown_requested = False
        self._consumer: Optional[ConfluentConsumer] = None
        self._dlq_producer: Optional[_KafkaProducer] = None
        self._buffer = BatchBuffer(config)
        self._writer: Optional[WebhookParquetWriter] = None

    def _get_writer(self) -> WebhookParquetWriter:
        if self._writer is None:
            self._writer = WebhookParquetWriter()
        return self._writer

    def _setup_signal_handlers(self) -> None:
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
        if self._buffer.total_messages > 0:
            self._flush_all("revoke")

    def _get_dlq_producer(self) -> _KafkaProducer:
        if self._dlq_producer is None:
            self._dlq_producer = _KafkaProducer(
                kafka_hosts=self._kafka_hosts,
                kafka_security_protocol=self._kafka_security_protocol,
            )
        return self._dlq_producer

    def _send_to_dlq(self, raw_message: bytes | dict, error: Exception) -> None:
        try:
            producer = self._get_dlq_producer()

            if isinstance(raw_message, bytes):
                try:
                    original = json.loads(raw_message.decode("utf-8"))
                except Exception:
                    original = raw_message.decode("utf-8", errors="replace")
            else:
                original = raw_message

            dlq_message = {
                "original_message": original,
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

            WEBHOOK_DLQ_MESSAGES_TOTAL.labels(error_type=type(error).__name__).inc()

            logger.warning(
                "message_sent_to_dlq",
                dlq_topic=self._config.dlq_topic,
                error_type=type(error).__name__,
                error_message=str(error),
            )
        except Exception as dlq_error:
            logger.exception("dlq_send_failed", original_error_type=type(error).__name__)
            capture_exception(dlq_error)
            raise

    def _send_buffer_to_dlq(self, schema_buffer: SchemaBuffer, error: Exception) -> None:
        """Send all messages in a schema buffer to the DLQ after S3 write retries are exhausted."""
        for payload_json in schema_buffer.payloads:
            message = {
                "team_id": schema_buffer.team_id,
                "schema_id": schema_buffer.schema_id,
                "payload": payload_json,
            }
            self._send_to_dlq(message, error)

    def run(self, health_reporter: Optional[Callable[[], None]] = None) -> None:
        self._setup_signal_handlers()

        logger.info(
            "consumer_starting",
            input_topic=self._config.input_topic,
            consumer_group=self._config.consumer_group,
            flush_interval_seconds=self._config.flush_interval_seconds,
            max_batch_messages=self._config.max_batch_messages,
            max_buffer_size_bytes=self._config.max_buffer_size_bytes,
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
                    num_messages=self._config.poll_batch_size,
                    timeout=self._config.poll_timeout_seconds,
                )

                for msg in raw_messages:
                    err = msg.error()
                    if err is not None:
                        if err.code() == KafkaError._PARTITION_EOF:
                            continue
                        logger.error("kafka_message_error", error=err)
                        continue
                    raw = msg.value()
                    if raw is None:
                        continue
                    self._process_message(raw)

                WEBHOOK_BUFFER_MESSAGE_COUNT.set(self._buffer.total_messages)
                WEBHOOK_BUFFER_SIZE_BYTES.set(self._buffer.total_size_bytes)

                flush_trigger = self._buffer.should_flush()
                if flush_trigger:
                    self._flush_all(flush_trigger)

            # Graceful shutdown: flush remaining
            if self._buffer.total_messages > 0:
                logger.info("flushing_remaining_on_shutdown", message_count=self._buffer.total_messages)
                self._flush_all("shutdown")

        except Exception as e:
            logger.exception("consumer_error")
            capture_exception(e)
            raise
        finally:
            self._cleanup()

    def _process_message(self, raw: bytes) -> None:
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._send_to_dlq(raw, e)
            return

        team_id = data.get("team_id")
        schema_id = data.get("schema_id")
        payload = data.get("payload")

        if not isinstance(team_id, int):
            self._send_to_dlq(raw, ValueError(f"team_id must be int, got {type(team_id).__name__}"))
            return
        if not isinstance(schema_id, str) or not schema_id:
            self._send_to_dlq(raw, ValueError(f"schema_id must be non-empty str, got {type(schema_id).__name__}"))
            return
        if not isinstance(payload, str):
            self._send_to_dlq(raw, ValueError(f"payload must be str, got {type(payload).__name__}"))
            return

        self._buffer.add(team_id, schema_id, payload)
        WEBHOOK_MESSAGES_BUFFERED_TOTAL.labels(team_id=str(team_id)).inc()

    def _write_buffer_with_retry(self, schema_buffer: SchemaBuffer) -> Optional[Exception]:
        """Write a single schema buffer to S3 with retry logic. Returns None on success, or the final error."""
        writer = self._get_writer()
        table = schema_buffer.to_arrow_table()

        for attempt in range(self._config.max_retries):
            try:
                with WEBHOOK_PARQUET_WRITE_DURATION_SECONDS.time():
                    s3_path = writer.write(table, schema_buffer.team_id, schema_buffer.schema_id)

                WEBHOOK_PARQUET_WRITES_TOTAL.labels(
                    team_id=str(schema_buffer.team_id),
                    status="success",
                ).inc()

                logger.debug(
                    "parquet_written",
                    team_id=schema_buffer.team_id,
                    schema_id=schema_buffer.schema_id,
                    row_count=len(schema_buffer),
                    s3_path=s3_path,
                )
                return None

            except S3_TRANSIENT_ERRORS as e:
                if attempt < self._config.max_retries - 1:
                    backoff = self._config.retry_backoff_seconds * (2**attempt)
                    logger.warning(
                        "s3_write_transient_error_retrying",
                        attempt=attempt + 1,
                        max_retries=self._config.max_retries,
                        backoff_seconds=backoff,
                        error_type=type(e).__name__,
                        team_id=schema_buffer.team_id,
                        schema_id=schema_buffer.schema_id,
                    )
                    time.sleep(backoff)
                else:
                    WEBHOOK_PARQUET_WRITES_TOTAL.labels(
                        team_id=str(schema_buffer.team_id),
                        status="failure",
                    ).inc()
                    logger.exception(
                        "s3_write_failed_after_retries",
                        attempts=self._config.max_retries,
                        team_id=schema_buffer.team_id,
                        schema_id=schema_buffer.schema_id,
                    )
                    capture_exception(e)
                    return e

            except Exception as e:
                WEBHOOK_PARQUET_WRITES_TOTAL.labels(
                    team_id=str(schema_buffer.team_id),
                    status="failure",
                ).inc()
                logger.exception(
                    "s3_write_failed",
                    team_id=schema_buffer.team_id,
                    schema_id=schema_buffer.schema_id,
                )
                capture_exception(e)
                return e

        return None  # unreachable, but satisfies type checker

    def _flush_all(self, trigger: str) -> None:
        assert self._consumer is not None

        buffers = self._buffer.get_buffers()
        if not buffers:
            self._buffer.clear()
            return

        WEBHOOK_FLUSH_TOTAL.labels(trigger=trigger).inc()

        logger.info(
            "flush_starting",
            trigger=trigger,
            buffer_count=len(buffers),
            total_messages=self._buffer.total_messages,
            total_size_bytes=self._buffer.total_size_bytes,
        )

        # Write all buffers concurrently
        with ThreadPoolExecutor(max_workers=min(len(buffers), 8)) as executor:
            futures = {
                executor.submit(self._write_buffer_with_retry, schema_buffer): key
                for key, schema_buffer in buffers.items()
            }

            for future in as_completed(futures):
                key = futures[future]
                error = future.result()
                if error is not None:
                    schema_buffer = buffers[key]
                    self._send_buffer_to_dlq(schema_buffer, error)

        # Commit offsets after all buffers are processed
        try:
            self._consumer.commit(asynchronous=False)
            WEBHOOK_OFFSET_COMMITS_TOTAL.labels(status="success").inc()
        except Exception:
            WEBHOOK_OFFSET_COMMITS_TOTAL.labels(status="failure").inc()
            raise

        logger.info("flush_complete", trigger=trigger, buffer_count=len(buffers))

        self._buffer.clear()
        WEBHOOK_BUFFER_MESSAGE_COUNT.set(0)
        WEBHOOK_BUFFER_SIZE_BYTES.set(0)

    def _cleanup(self) -> None:
        logger.info("consumer_shutting_down")

        if self._dlq_producer:
            try:
                self._dlq_producer.flush(timeout=10.0)
            except Exception as e:
                logger.exception("dlq_producer_flush_failed")
                capture_exception(e)

        if self._consumer:
            try:
                self._consumer.close()
                logger.info("consumer_closed")
            except Exception as e:
                logger.exception("consumer_close_failed")
                capture_exception(e)

        logger.info("consumer_shutdown_complete")
