"""Throttling consumer for warehouse -> person-property $set intents.

Drains ``KAFKA_WAREHOUSE_PERSON_PROPERTY_UPDATES`` and sends each as a ``$set`` through
capture-internal, at a global rate (a constance setting ops can retune live). The topic is keyed
by ``team_id`` so a big team's backlog only delays itself; there's no per-team rate limiting in v1.
Kafka lag is the backpressure. Offsets commit only after a successful send; permanently-rejected
(poison) messages go to a DLQ so they can't wedge a partition.

The rate limiter and the message->capture mapping are pure and unit-tested; the Kafka loop and
capture call are the boundaries.
"""

import json
import time
import signal
from collections.abc import Callable
from typing import Any

import structlog
from prometheus_client import Counter

from posthog.kafka_client.client import _KafkaSecurityProtocol
from posthog.kafka_client.routing import get_producer, get_profile_settings
from posthog.kafka_client.topics import (
    KAFKA_WAREHOUSE_PERSON_PROPERTY_UPDATES,
    KAFKA_WAREHOUSE_PERSON_PROPERTY_UPDATES_DLQ,
)
from posthog.models.instance_setting import get_instance_setting

logger = structlog.get_logger(__name__)

CONSUMER_GROUP = "warehouse-person-property-updates"
_RATE_SETTING = "WAREHOUSE_PERSON_PROPERTY_SET_RATE_PER_SEC"
EVENT_SOURCE = "customer_analytics_person_property_sync"

SENT_TOTAL = Counter("warehouse_person_property_sent_total", "person-property $set events sent to capture")
DLQ_TOTAL = Counter("warehouse_person_property_dlq_total", "person-property update messages routed to DLQ")
DLQ_FAILED_TOTAL = Counter(
    "warehouse_person_property_dlq_failed_total", "person-property DLQ writes that failed to deliver"
)
RETRY_TOTAL = Counter("warehouse_person_property_retry_total", "person-property update messages left for redelivery")

# How long to wait for a DLQ produce to be acknowledged before treating it as failed.
_DLQ_DELIVERY_TIMEOUT_SECONDS = 30.0

# Pause between in-place retries of a transiently-failing message (capture down / timeout).
_RETRY_BACKOFF_SECONDS = 1.0


class InvalidPersonPropertyMessage(Exception):
    """A message that can never succeed (bad shape) -> DLQ, not retry."""


class TokenBucket:
    """Global token-bucket rate limiter. ``rate`` is re-read each acquire so a live constance change
    takes effect without a restart. ``sleep``/``now`` are injectable for tests."""

    def __init__(
        self,
        rate_fn: Callable[[], float],
        *,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._rate_fn = rate_fn
        self._now = now
        self._sleep = sleep
        self._tokens = 0.0
        self._last = now()

    def _refill(self) -> float:
        rate = max(1.0, float(self._rate_fn()))
        current = self._now()
        elapsed = max(0.0, current - self._last)
        self._last = current
        self._tokens = min(rate, self._tokens + elapsed * rate)
        return rate

    def acquire(self) -> None:
        """Block until one token is available."""
        rate = self._refill()
        while self._tokens < 1.0:
            self._sleep((1.0 - self._tokens) / rate)
            rate = self._refill()
        self._tokens -= 1.0


def build_capture_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    """Map a topic message to capture_internal kwargs. Raises InvalidPersonPropertyMessage for a
    shape that can never succeed (missing token/distinct_id, or no properties)."""
    token = payload.get("token")
    distinct_id = payload.get("distinct_id")
    properties = payload.get("properties")
    if not token or not distinct_id:
        raise InvalidPersonPropertyMessage("message missing token or distinct_id")
    if not isinstance(properties, dict) or not properties:
        raise InvalidPersonPropertyMessage("message has no properties to set")
    return {
        "token": token,
        "event_name": "$set",
        "event_source": payload.get("event_source") or EVENT_SOURCE,
        "distinct_id": str(distinct_id),
        "properties": {"$set": properties},
        "process_person_profile": True,
    }


def _current_rate() -> float:
    return float(get_instance_setting(_RATE_SETTING))


# Outcomes of handling one message. "sent" and "dlq" are terminal (commit the offset); "retry"
# leaves the offset uncommitted so the message is redelivered.
SENT = "sent"
DLQ = "dlq"
RETRY = "retry"


class PersonPropertyUpdateConsumer:
    def __init__(
        self,
        *,
        capture_fn: Callable[..., Any] | None = None,
        bucket: TokenBucket | None = None,
        dlq_producer: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # Lazy default import so tests can inject without importing the capture stack.
        if capture_fn is None:
            from posthog.api.capture import capture_internal  # noqa: PLC0415

            capture_fn = capture_internal
        self._capture = capture_fn
        self._bucket = bucket or TokenBucket(_current_rate)
        self._dlq_producer = dlq_producer
        self._sleep = sleep
        self._shutdown = False

    def _get_dlq_producer(self) -> Any:
        # Reuse the routed, process-wide singleton producer for the DLQ topic rather than
        # constructing one per message (Kafka producers are heavyweight). Resolved lazily so a
        # consumer that never hits a poison message never opens a producer, and tests inject their
        # own without touching the Kafka stack.
        if self._dlq_producer is None:
            self._dlq_producer = get_producer(topic=KAFKA_WAREHOUSE_PERSON_PROPERTY_UPDATES_DLQ)
        return self._dlq_producer

    def _dlq(self, value: bytes, reason: str) -> str:
        """Route a poison message to the DLQ. Returns ``DLQ`` only once the write is confirmed
        delivered; a failed DLQ write returns ``RETRY`` so the source offset stays uncommitted and
        the message is redelivered rather than silently dropped from both topics."""
        logger.warning("person_property_update.dlq", reason=reason)
        producer = self._get_dlq_producer()
        result = producer.produce(
            topic=KAFKA_WAREHOUSE_PERSON_PROPERTY_UPDATES_DLQ,
            data={"raw": value.decode("utf-8", "replace"), "reason": reason},
        )
        producer.flush()
        try:
            result.get(timeout=_DLQ_DELIVERY_TIMEOUT_SECONDS)
        except Exception:
            DLQ_FAILED_TOTAL.inc()
            logger.exception("person_property_update.dlq_delivery_failed", reason=reason)
            return RETRY
        DLQ_TOTAL.inc()
        return DLQ

    def process_record(self, value: bytes) -> str:
        """Handle one message. Terminal outcomes (sent/dlq) commit; retry does not."""
        try:
            payload = json.loads(value)
        except (ValueError, TypeError):
            return self._dlq(value, "invalid_json")
        # Valid JSON that isn't an object (``[]``, ``"foo"``, ``null``) parses fine but can never map
        # to a $set; DLQ it instead of letting build_capture_kwargs crash and wedge the partition.
        if not isinstance(payload, dict):
            return self._dlq(value, "payload_not_object")
        try:
            kwargs = build_capture_kwargs(payload)
        except InvalidPersonPropertyMessage as exc:
            return self._dlq(value, str(exc))

        # Pace the send. Blocks (via the bucket's sleep) until a token frees up; Kafka lag absorbs
        # the wait so we never drop a message.
        self._bucket.acquire()
        try:
            result = self._capture(**kwargs)
        except Exception:
            # Transient (capture unreachable, timeout): leave uncommitted for redelivery.
            RETRY_TOTAL.inc()
            logger.exception("person_property_update.capture_error")
            return RETRY
        if result.succeeded():
            SENT_TOTAL.inc()
            return SENT
        # A drop is terminal: capture rejected the event permanently (e.g. invalid/stale token,
        # validation failure), so it's poison. DLQ it rather than redelivering forever. Everything
        # else (exhausted retries, unaccounted, whole-request error) is transient -> leave for retry.
        if result.dropped:
            return self._dlq(value, "capture_dropped")
        RETRY_TOTAL.inc()
        return RETRY

    def _process_with_retries(self, value: bytes) -> str:
        """Process one message, retrying transient failures in place. A ``RETRY`` must never
        advance past the message: Kafka offset commits are a high-water mark, so committing a
        later message's offset would silently skip this one. We re-send the same message (Kafka
        lag is the backpressure) until it's terminal, or return ``RETRY`` if shutdown is requested
        mid-retry so the uncommitted offset is redelivered on the next start."""
        outcome = self.process_record(value)
        while outcome == RETRY and not self._shutdown:
            self._sleep(_RETRY_BACKOFF_SECONDS)
            outcome = self.process_record(value)
        return outcome

    def run(self, poll_timeout: float = 1.0) -> None:  # pragma: no cover - exercised in dogfood
        from confluent_kafka import Consumer as ConfluentConsumer  # noqa: PLC0415

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda *_: setattr(self, "_shutdown", True))
            except ValueError:
                pass

        # Resolve hosts + TLS/SASL through the router so the input topic's cluster profile (and any
        # KAFKA_TOPIC_ROUTING_OVERRIDES) applies — never a bare plaintext KAFKA_HOSTS connection.
        profile = get_profile_settings(topic=KAFKA_WAREHOUSE_PERSON_PROPERTY_UPDATES)
        config: dict[str, str | int | float | bool | None] = {
            "bootstrap.servers": ",".join(profile.hosts),
            "group.id": CONSUMER_GROUP,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "security.protocol": profile.security_protocol or _KafkaSecurityProtocol.PLAINTEXT,
        }
        if profile.security_protocol in (_KafkaSecurityProtocol.SASL_PLAINTEXT, _KafkaSecurityProtocol.SASL_SSL):
            config["sasl.mechanism"] = profile.sasl_mechanism
            config["sasl.username"] = profile.sasl_user
            config["sasl.password"] = profile.sasl_password
        consumer = ConfluentConsumer(config)
        consumer.subscribe([KAFKA_WAREHOUSE_PERSON_PROPERTY_UPDATES])
        logger.info("person_property_update.consumer_started")
        try:
            while not self._shutdown:
                message = consumer.poll(poll_timeout)
                if message is None:
                    continue
                if message.error():
                    logger.warning("person_property_update.kafka_error", error=str(message.error()))
                    continue
                value = message.value()
                if value is None:
                    # Tombstone / empty payload: nothing to $set. Commit past it so it doesn't replay.
                    consumer.commit(message=message, asynchronous=False)
                    continue
                outcome = self._process_with_retries(value)
                if outcome in (SENT, DLQ):
                    consumer.commit(message=message, asynchronous=False)
        finally:
            consumer.close()
            logger.info("person_property_update.consumer_stopped")
