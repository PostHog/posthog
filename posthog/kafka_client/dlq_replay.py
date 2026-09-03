from collections.abc import Callable, Sequence
from typing import Any, Optional, cast

from confluent_kafka import Consumer, Producer

from posthog.kafka_client.routing import get_profile_settings

Header = tuple[str, bytes]

# Diagnostic headers the logs/traces ingestion consumer attaches when it quarantines a
# message. They describe the old failure and must not travel back onto the target topic.
DLQ_DIAGNOSTIC_HEADERS = frozenset(
    {
        "error_message",
        "error_name",
        "failed_at",
        "source_topic",
        "source_partition",
        "source_offset",
    }
)

# Counts how many times a message has been replayed, so a message that keeps failing is
# left on the DLQ instead of cycling between the two topics.
REPLAY_COUNT_HEADER = "dlq_replay_count"


def _replay_count(headers: Sequence[Header]) -> int:
    for key, value in headers:
        if key == REPLAY_COUNT_HEADER:
            try:
                return int(value.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return 0
    return 0


def build_replay_headers(headers: Optional[Sequence[Header]], max_replays: int) -> Optional[list[Header]]:
    """Return the headers to replay with, or None when the message is exhausted.

    Strips the DLQ diagnostic headers, keeps the original ones, and increments the
    replay-count guard. Returns None when the message has already been replayed
    max_replays times, so the caller leaves it on the DLQ.
    """
    existing = list(headers or [])
    count = _replay_count(existing)
    if count >= max_replays:
        return None
    kept = [
        (key, value) for (key, value) in existing if key not in DLQ_DIAGNOSTIC_HEADERS and key != REPLAY_COUNT_HEADER
    ]
    kept.append((REPLAY_COUNT_HEADER, str(count + 1).encode("utf-8")))
    return kept


def _client_config(
    hosts: list[str],
    security_protocol: Optional[str],
    sasl_mechanism: Optional[str],
    sasl_user: Optional[str],
    sasl_password: Optional[str],
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "bootstrap.servers": ",".join(hosts),
        "security.protocol": security_protocol or "PLAINTEXT",
    }
    if sasl_mechanism:
        config["sasl.mechanism"] = sasl_mechanism
        if sasl_user:
            config["sasl.username"] = sasl_user
        if sasl_password:
            config["sasl.password"] = sasl_password
    return config


def drain_dlq(
    *,
    source_topic: str,
    target_topic: str,
    group_id: str,
    max_replays: int = 2,
    batch_size: int = 500,
    idle_polls: int = 2,
    poll_timeout_seconds: float = 5.0,
    dry_run: bool = False,
    bootstrap_servers: Optional[str] = None,
    security_protocol: Optional[str] = None,
    log: Callable[[str], None] = print,
) -> dict[str, int]:
    """Drain a Kafka DLQ topic back into its target topic using a consumer group.

    Reads the source topic with a committed consumer group (so progress is resumable and
    visible as lag), reproduces each message to the target with the diagnostic headers
    stripped, and stops once the topic is drained (idle_polls consecutive empty polls).
    Commits a batch only after the broker acknowledges every record in it, so an
    interrupted run resumes rather than replaying from the start, and a record the broker
    rejected stays on the DLQ. A dry run counts without producing or committing.
    """
    source = get_profile_settings(topic=source_topic)
    target = get_profile_settings(topic=target_topic)

    consumer_hosts = [bootstrap_servers] if bootstrap_servers else source.hosts
    producer_hosts = [bootstrap_servers] if bootstrap_servers else target.hosts

    consumer_conf: dict[str, Any] = {
        **_client_config(
            consumer_hosts,
            security_protocol or source.security_protocol,
            source.sasl_mechanism,
            source.sasl_user,
            source.sasl_password,
        ),
        "group.id": group_id,
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
    }

    consumer = Consumer(consumer_conf)
    producer: Optional[Producer] = None
    if not dry_run:
        producer_conf: dict[str, Any] = {
            **_client_config(
                producer_hosts,
                security_protocol or target.security_protocol,
                target.sasl_mechanism,
                target.sasl_user,
                target.sasl_password,
            ),
            "acks": "all",
        }
        producer = Producer(producer_conf)

    replayed = 0
    exhausted = 0
    errors = 0
    # confluent-kafka reports a rejected record through the delivery callback, not through
    # produce() or flush(). Without this the run would commit offsets for records the
    # broker never took, and those records would be gone from the next replay.
    delivery_failures: list[str] = []

    def on_delivery(err: Any, _message: Any) -> None:
        if err is not None:
            delivery_failures.append(str(err))

    try:
        consumer.subscribe([source_topic])
        idle = 0
        while True:
            messages = consumer.consume(num_messages=batch_size, timeout=poll_timeout_seconds)
            if not messages:
                idle += 1
                if idle >= idle_polls:
                    break
                continue
            idle = 0

            delivery_failures.clear()
            produced_in_batch = 0
            for message in messages:
                err = message.error()
                if err is not None:
                    errors += 1
                    log(f"consume error: {err}")
                    continue

                raw_headers = cast(Optional[list[Header]], message.headers())
                headers = build_replay_headers(raw_headers, max_replays)
                if headers is None:
                    exhausted += 1
                    continue

                if dry_run or producer is None:
                    replayed += 1
                    continue

                _produce(producer, target_topic, message.value(), headers, on_delivery, log)
                produced_in_batch += 1

            if producer is not None:
                producer.flush()
                failed = len(delivery_failures)
                replayed += produced_in_batch - failed
                errors += failed
                if failed:
                    log(f"delivery failed for {failed} record(s); stopping without commit: {delivery_failures[0]}")
                    break
                # Commit even when the batch produced nothing, because a batch of records
                # that all hit max_replays would otherwise hold the group behind it and the
                # lag would never reach zero.
                consumer.commit(asynchronous=False)

            log(f"progress: replayed={replayed} exhausted={exhausted} errors={errors}")
    finally:
        consumer.close()
        if producer is not None:
            producer.flush()

    log(f"done: replayed={replayed} exhausted={exhausted} errors={errors} dry_run={dry_run}")
    return {"replayed": replayed, "exhausted": exhausted, "errors": errors}


def _produce(
    producer: Producer,
    topic: str,
    value: Optional[bytes],
    headers: list[Header],
    on_delivery: Callable[[Any, Any], None],
    log: Callable[[str], None],
) -> None:
    while True:
        try:
            producer.produce(
                topic=topic,
                value=value,
                key=None,
                headers=cast(Any, headers),
                on_delivery=on_delivery,
            )
            return
        except BufferError:
            # Local produce queue is full; let it drain, then retry the same message.
            producer.poll(1.0)
