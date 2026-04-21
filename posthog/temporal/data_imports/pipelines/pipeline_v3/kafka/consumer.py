import json
import time
import signal
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Optional

from django.conf import settings

import structlog
import posthoganalytics
from confluent_kafka import (
    Consumer as ConfluentConsumer,
    KafkaError,
    KafkaException,
)

from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.client import _KafkaProducer, _KafkaSecurityProtocol
from posthog.temporal.data_imports.pipelines.pipeline_v3.kafka.metrics import (
    BATCH_PROCESSING_DURATION_SECONDS,
    BATCH_RETRY_EXHAUSTED_TOTAL,
    BATCH_RETRY_TOTAL,
    BATCH_SIZE,
    BATCH_UTILIZATION,
    DLQ_MESSAGES_TOTAL,
    MESSAGES_PROCESSED_TOTAL,
    OFFSET_COMMITS_TOTAL,
)
from posthog.temporal.data_imports.pipelines.pipeline_v3.load.config import ConsumerConfig
from posthog.temporal.data_imports.pipelines.pipeline_v3.load.retry_tracker import (
    TRANSIENT_ERRORS,
    RetryExhaustedError,
    classify_error,
    clear_retry_info,
    get_retry_info,
    increment_retry_count,
    is_retry_exhausted,
    update_retry_error_type,
)
from posthog.utils import get_machine_id

logger = structlog.get_logger(__name__)


def _extract_message_key(message: dict) -> Optional[tuple[int, str, str, int]]:
    """Extract retry tracking key fields from a message.

    Returns (team_id, schema_id, run_uuid, batch_index) or None if fields are missing.
    """
    try:
        return (message["team_id"], message["schema_id"], message["run_uuid"], message["batch_index"])
    except (KeyError, TypeError):
        return None


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
        process_message: Callable[..., None],
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
            "partition.assignment.strategy": "cooperative-sticky",
        }
        consumer = ConfluentConsumer(config)
        consumer.subscribe(
            [self._config.input_topic],
            on_assign=self._on_assign,
            on_revoke=self._on_revoke,
            on_lost=self._on_lost,
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
        """Graceful revoke during a cooperative-sticky rebalance.

        With cooperative-sticky the callback fires only for the partitions
        actually being revoked; other assignments stay put. The synchronous
        consume loop calls back here *between* batches, so there's no
        in-flight processing to drain at this point. Commit stored offsets
        so the next owner picks up from where we stopped.
        """
        logger.info(
            "partition_revocation_starting",
            revoked_partition_count=len(partitions),
            revoked_partitions=[{"topic": p.topic, "partition": p.partition} for p in partitions],
        )
        try:
            consumer.commit(asynchronous=False)
        except KafkaException as e:
            kafka_error = e.args[0]
            if hasattr(kafka_error, "code") and kafka_error.code() == KafkaError._NO_OFFSET:  # type: ignore[attr-defined]
                logger.debug("no_offsets_to_commit_on_revoke")
            else:
                logger.warning("failed_to_commit_on_revoke", error=str(e))
        except Exception as e:
            logger.warning("failed_to_commit_on_revoke", error=str(e))
        logger.info("partition_revocation_complete", revoked_partition_count=len(partitions))

    def _on_lost(self, consumer: ConfluentConsumer, partitions: list) -> None:
        """Involuntary partition loss (session timeout, network blip, etc.).

        Do NOT commit: another consumer may already own these partitions,
        and committing here could cause the new owner to skip messages we
        never finished processing.
        """
        logger.warning(
            "partitions_lost",
            lost_partition_count=len(partitions),
            lost_partitions=[{"topic": p.topic, "partition": p.partition} for p in partitions],
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

            posthoganalytics.capture(
                distinct_id=get_machine_id(),
                event="warehouse_v3_dlq_message",
                properties={
                    "team_id": message.get("team_id") if isinstance(message, dict) else None,
                    "schema_id": message.get("schema_id") if isinstance(message, dict) else None,
                    "error_type": type(error).__name__,
                    "input_topic": self._config.input_topic,
                },
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

                BATCH_UTILIZATION.labels(group_id=self._config.consumer_group).set(
                    len(raw_messages) / self._config.batch_size
                )

                messages: list[tuple[Any, dict]] = []
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
                    messages.append((msg, json.loads(raw.decode("utf-8"))))

                if not messages:
                    continue

                BATCH_SIZE.observe(len(messages))

                logger.debug("batch_received", message_count=len(messages))

                self._process_batch_with_retry(messages, health_reporter=health_reporter)

        except Exception as e:
            logger.exception("consumer_error")
            capture_exception(e)
            raise
        finally:
            self._cleanup()

    def _commit_message(self, raw_msg: Any) -> None:
        """Commit the offset for a single Kafka message synchronously.

        Used on DLQ paths so a stuck message doesn't block the offset commit of
        its healthy siblings in the same batch. Failures are logged but swallowed
        so a commit blip doesn't prevent continued processing — redelivery will
        hit the is_retry_exhausted branch and re-DLQ idempotently.
        """
        assert self._consumer is not None
        try:
            self._consumer.commit(message=raw_msg, asynchronous=False)
            OFFSET_COMMITS_TOTAL.labels(status="success").inc()
        except Exception as e:
            OFFSET_COMMITS_TOTAL.labels(status="failure").inc()
            logger.warning("per_message_commit_failed", error=str(e))

    def _process_batch_with_retry(
        self, messages: list[tuple[Any, dict]], health_reporter: Optional[Callable[[], None]] = None
    ) -> None:
        """Process a batch of messages with persistent retry tracking.

        Each message's retry count is tracked in Redis so that retries survive
        OOM process crashes. On each delivery the counter is pre-incremented
        before processing, so a crash mid-processing still counts as an attempt.

        Transient errors (DB connection, network) get up to 9 attempts.
        Non-transient or unknown errors (including OOM crashes) get up to 3.
        When retries are exhausted the message goes to the DLQ and the job is
        marked as failed.
        """
        assert self._consumer is not None

        dlq_count = 0

        for raw_msg, message in messages:
            team_id = str(message.get("team_id") or "unknown")
            schema_id = str(message.get("schema_id") or "unknown")

            msg_key = _extract_message_key(message)

            if msg_key is None:
                # Can't track retries without identifiers — process directly
                with BATCH_PROCESSING_DURATION_SECONDS.labels(team_id=team_id, schema_id=schema_id).time():
                    self._process_message(message, progress_callback=health_reporter)
                MESSAGES_PROCESSED_TOTAL.labels(team_id=team_id, schema_id=schema_id, status="success").inc()
                if health_reporter:
                    health_reporter()
                continue

            # Check if retries are already exhausted from a previous delivery
            retry_info = get_retry_info(*msg_key)
            if is_retry_exhausted(retry_info):
                error = RetryExhaustedError(retry_info)
                logger.warning(
                    "retry_exhausted",
                    team_id=team_id,
                    schema_id=schema_id,
                    retry_count=retry_info.count,
                    error_type=retry_info.error_type,
                    last_error=retry_info.last_error,
                )
                self._send_to_dlq(message, error)
                self._mark_job_failed_from_message(message, error)
                # Deliberately keep retry_info in Redis: if this per-message
                # commit or the trailing batch commit fails, redelivery must
                # still observe the exhausted state and re-DLQ idempotently
                # rather than starting a fresh retry cycle. Cleanup relies on
                # the 72h TTL.
                self._commit_message(raw_msg)
                MESSAGES_PROCESSED_TOTAL.labels(team_id=team_id, schema_id=schema_id, status="dlq").inc()
                DLQ_MESSAGES_TOTAL.labels(team_id=team_id, schema_id=schema_id, error_type="RetryExhausted").inc()
                BATCH_RETRY_EXHAUSTED_TOTAL.labels(error_type=retry_info.error_type or "unknown").inc()
                dlq_count += 1
                continue

            # Pre-increment counter before processing (survives OOM)
            retry_info = increment_retry_count(*msg_key)

            try:
                self._process_single_with_inprocess_retry(message, health_reporter)

                # Success — clear retry info
                clear_retry_info(*msg_key)
                MESSAGES_PROCESSED_TOTAL.labels(team_id=team_id, schema_id=schema_id, status="success").inc()

            except Exception as e:
                # Classify error and persist to Redis
                error_class = classify_error(e)
                update_retry_error_type(*msg_key, error_type=error_class, last_error=str(e))

                capture_exception(e)
                logger.exception(
                    "message_processing_failed",
                    error_type=type(e).__name__,
                    error_class=error_class,
                    retry_count=retry_info.count,
                )

                BATCH_RETRY_TOTAL.labels(attempt=str(retry_info.count), error_type=type(e).__name__).inc()

                if is_retry_exhausted(retry_info):
                    # Exhausted after this attempt — DLQ and mark failed.
                    # Retry state stays in Redis (72h TTL) so that if the
                    # per-message commit or a sibling failure prevents the
                    # trailing batch commit, redelivery will re-DLQ via the
                    # is_retry_exhausted branch rather than retrying from zero.
                    self._send_to_dlq(message, e)
                    self._mark_job_failed_from_message(message, e)
                    self._commit_message(raw_msg)
                    MESSAGES_PROCESSED_TOTAL.labels(team_id=team_id, schema_id=schema_id, status="dlq").inc()
                    DLQ_MESSAGES_TOTAL.labels(team_id=team_id, schema_id=schema_id, error_type=type(e).__name__).inc()
                    BATCH_RETRY_EXHAUSTED_TOTAL.labels(error_type=error_class).inc()
                    dlq_count += 1
                else:
                    # Not exhausted — re-raise to prevent offset commit.
                    # Kafka will redeliver the entire batch; already-processed
                    # messages are skipped by the idempotency check.
                    raise

        # All messages handled (success or DLQ) — commit offsets
        try:
            self._consumer.commit()
            OFFSET_COMMITS_TOTAL.labels(status="success").inc()
        except Exception:
            OFFSET_COMMITS_TOTAL.labels(status="failure").inc()
            raise
        processed = len(messages) - dlq_count
        logger.debug("batch_committed", message_count=processed, dlq_count=dlq_count)

    def _process_single_with_inprocess_retry(
        self, message: Any, health_reporter: Optional[Callable[[], None]] = None
    ) -> None:
        """Process a single message with in-process retries for transient errors.

        This handles fast-recovering transient errors (e.g. brief DB connection
        blip) without needing a full Kafka redeliver cycle. The persistent retry
        tracker in Redis is the outer safety net for process crashes.
        """
        team_id = str(message.get("team_id") or "unknown")
        schema_id = str(message.get("schema_id") or "unknown")
        for attempt in range(self._config.max_retries):
            try:
                with BATCH_PROCESSING_DURATION_SECONDS.labels(team_id=team_id, schema_id=schema_id).time():
                    self._process_message(message, progress_callback=health_reporter)
                if health_reporter:
                    health_reporter()
                return
            except TRANSIENT_ERRORS as e:
                BATCH_RETRY_TOTAL.labels(attempt=str(attempt + 1), error_type=type(e).__name__).inc()
                if attempt == self._config.max_retries - 1:
                    raise
                backoff = self._config.retry_backoff_seconds * (2**attempt)
                logger.warning(
                    "transient_error_inprocess_retry",
                    attempt=attempt + 1,
                    max_retries=self._config.max_retries,
                    backoff_seconds=backoff,
                    error_type=type(e).__name__,
                )
                time.sleep(backoff)

    def _mark_job_failed_from_message(self, message: Any, error: Exception) -> None:
        """Mark the job as failed when persistent retries are exhausted."""
        try:
            from posthog.temporal.data_imports.pipelines.pipeline_v3.kafka.common import ExportSignalMessage
            from posthog.temporal.data_imports.pipelines.pipeline_v3.load.processor import _mark_job_failed

            export_signal = ExportSignalMessage.from_dict(message)
            _mark_job_failed(export_signal, error)
        except Exception as e:
            logger.exception("failed_to_mark_job_failed", error_type=type(e).__name__)
            capture_exception(e)

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
