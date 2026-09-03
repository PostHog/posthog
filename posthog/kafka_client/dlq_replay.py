import time
from collections.abc import Callable, Sequence
from typing import Any, Optional, cast

from confluent_kafka import Consumer, KafkaException, Producer

from posthog.kafka_client.routing import get_profile_settings

Header = tuple[str, bytes]

# The logs/traces ingestion consumer records the resolved team on every quarantined
# message, so a replay can read past a team's records without reproducing them.
TEAM_ID_HEADER = "team_id"

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


def _team_id(headers: Sequence[Header]) -> Optional[int]:
    for key, value in headers:
        if key == TEAM_ID_HEADER:
            try:
                return int(value.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return None
    return None


def _throttle_delay(produced: int, max_messages_per_second: Optional[float], elapsed_seconds: float) -> float:
    """Seconds to wait so the produce rate stays at or below max_messages_per_second.

    Zero when no limit is set, nothing was produced, or the batch already took longer
    than the budget for its size.
    """
    if not max_messages_per_second or produced <= 0:
        return 0.0
    target_seconds = produced / max_messages_per_second
    return max(0.0, target_seconds - elapsed_seconds)


def classify_message(
    raw_headers: Optional[Sequence[Header]], skip_team_ids: frozenset[int], max_replays: int
) -> tuple[str, Optional[list[Header]]]:
    """Decide what to do with a DLQ message: skip, exhausted, or replay.

    Returns the replay headers only for "replay"; the other outcomes leave the message
    on the DLQ and carry no headers.
    """
    if skip_team_ids and _team_id(raw_headers or []) in skip_team_ids:
        return "skip", None
    headers = build_replay_headers(raw_headers, max_replays)
    if headers is None:
        return "exhausted", None
    return "replay", headers


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
    skip_team_ids: frozenset[int] = frozenset(),
    max_messages_per_second: Optional[float] = None,
    should_stop: Callable[[], bool] = lambda: False,
    log: Callable[[str], None] = print,
) -> dict[str, int]:
    """Drain a Kafka DLQ topic back into its target topic using a consumer group.

    Reads the source topic with a committed consumer group (so progress is resumable and
    visible as lag), reproduces each message to the target with the diagnostic headers
    stripped, and stops once the topic is drained (idle_polls consecutive empty polls).
    Commits a batch only after the broker acknowledges every record in it, so an
    interrupted run resumes rather than replaying from the start, and a record the broker
    rejected stays on the DLQ. A dry run counts without producing or committing.

    Records whose team is in skip_team_ids are read past without reproducing, so their
    offsets advance but they stay on the DLQ. max_messages_per_second caps the produce
    rate. should_stop is polled between batches so a caller can stop the run after the
    current batch commits, rather than abandoning it mid-flight.
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
    skipped = 0
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
            if should_stop():
                log("stop requested; exiting after the last committed batch")
                break

            batch_started = time.monotonic()
            messages = consumer.consume(num_messages=batch_size, timeout=poll_timeout_seconds)
            if not messages:
                # An empty poll while the group holds no partitions is a rebalance in
                # progress, not a drained topic. Only count idle polls once we have an
                # assignment, so a run that starts alongside others does not exit early.
                if not consumer.assignment():
                    continue
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
                action, headers = classify_message(raw_headers, skip_team_ids, max_replays)
                if action == "skip":
                    skipped += 1
                    continue
                if action == "exhausted":
                    exhausted += 1
                    continue

                if dry_run or producer is None or headers is None:
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
                # that all skipped or hit max_replays would otherwise hold the group behind
                # it and the lag would never reach zero.
                try:
                    consumer.commit(asynchronous=False)
                except KafkaException as commit_error:
                    # A rebalance can revoke this batch's partitions before the commit
                    # lands. The new owner re-reads from the last committed offset, so drop
                    # the commit and keep going rather than crash the run.
                    log(f"commit skipped after a likely rebalance; records will be re-read: {commit_error}")

            delay = _throttle_delay(produced_in_batch, max_messages_per_second, time.monotonic() - batch_started)
            if delay > 0:
                time.sleep(delay)

            log(f"progress: replayed={replayed} exhausted={exhausted} skipped={skipped} errors={errors}")
    finally:
        consumer.close()
        if producer is not None:
            producer.flush()

    log(f"done: replayed={replayed} exhausted={exhausted} skipped={skipped} errors={errors} dry_run={dry_run}")
    return {"replayed": replayed, "exhausted": exhausted, "skipped": skipped, "errors": errors}


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
