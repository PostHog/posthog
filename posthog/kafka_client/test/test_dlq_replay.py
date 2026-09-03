import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, Optional

from unittest import TestCase
from unittest.mock import patch

from confluent_kafka import KafkaError, KafkaException
from parameterized import parameterized

from posthog.kafka_client.dlq_replay import (
    REPLAY_COUNT_HEADER,
    _sleep_until,
    _throttle_delay,
    build_replay_headers,
    drain_dlq,
)

REBALANCE_IN_PROGRESS = KafkaError.REBALANCE_IN_PROGRESS  # type: ignore[attr-defined]
TIMED_OUT = KafkaError._TIMED_OUT  # type: ignore[attr-defined]


class BuildReplayHeadersTest(TestCase):
    def test_strips_diagnostics_keeps_originals_and_sets_first_replay_count(self) -> None:
        headers = [
            ("token", b"phc_abc"),
            ("team_id", b"42"),
            ("error_message", b"boom"),
            ("error_name", b"ValueError"),
            ("failed_at", b"2026-09-03T00:00:00Z"),
            ("source_topic", b"ingestion-traces"),
            ("source_partition", b"3"),
            ("source_offset", b"17"),
        ]

        result = build_replay_headers(headers, max_replays=2)

        assert result is not None
        as_dict = dict(result)
        assert as_dict == {"token": b"phc_abc", "team_id": b"42", REPLAY_COUNT_HEADER: b"1"}

    def test_none_headers_yields_only_replay_count(self) -> None:
        result = build_replay_headers(None, max_replays=2)
        assert result == [(REPLAY_COUNT_HEADER, b"1")]

    @parameterized.expand(
        [
            ("first_replay", 0, 2, b"1"),
            ("second_replay", 1, 2, b"2"),
            ("higher_cap", 3, 5, b"4"),
        ]
    )
    def test_increments_existing_replay_count(
        self, _name: str, current: int, max_replays: int, expected: bytes
    ) -> None:
        headers = [(REPLAY_COUNT_HEADER, str(current).encode("utf-8"))]

        result = build_replay_headers(headers, max_replays=max_replays)

        assert result is not None
        assert dict(result)[REPLAY_COUNT_HEADER] == expected
        assert sum(1 for key, _ in result if key == REPLAY_COUNT_HEADER) == 1

    @parameterized.expand(
        [
            ("at_cap", 2, 2),
            ("over_cap", 5, 2),
            ("zero_cap", 0, 0),
        ]
    )
    def test_returns_none_when_exhausted(self, _name: str, current: int, max_replays: int) -> None:
        headers = [(REPLAY_COUNT_HEADER, str(current).encode("utf-8"))]

        assert build_replay_headers(headers, max_replays=max_replays) is None

    def test_garbage_replay_count_treated_as_zero(self) -> None:
        result = build_replay_headers([(REPLAY_COUNT_HEADER, b"not-a-number")], max_replays=2)

        assert result is not None
        assert dict(result)[REPLAY_COUNT_HEADER] == b"1"


class FakeMessage:
    def __init__(self, value: bytes, headers: Optional[list[tuple[str, bytes]]] = None) -> None:
        self._value = value
        self._headers = headers

    def error(self) -> None:
        return None

    def headers(self) -> Optional[list[tuple[str, bytes]]]:
        return self._headers

    def value(self) -> bytes:
        return self._value


class FakeConsumer:
    def __init__(
        self,
        batches: list[list[FakeMessage]],
        assignments: Optional[list[list[str]]] = None,
        commit_error: Optional[Exception] = None,
    ) -> None:
        self._batches = list(batches)
        self._assignments = list(assignments) if assignments is not None else None
        self._commit_error = commit_error
        self.commits = 0

    def subscribe(self, _topics: list[str]) -> None:
        pass

    def consume(self, num_messages: int, timeout: float) -> list[FakeMessage]:
        return self._batches.pop(0) if self._batches else []

    def assignment(self) -> list[str]:
        if self._assignments is None:
            return ["tp"]
        return self._assignments.pop(0) if self._assignments else []

    def commit(self, asynchronous: bool = True) -> None:
        self.commits += 1
        if self._commit_error is not None:
            raise self._commit_error

    def close(self) -> None:
        pass


class FakeProducer:
    def __init__(self, delivery_error: Optional[str] = None) -> None:
        self.delivery_error = delivery_error
        self.produced: list[dict[str, Any]] = []
        self._pending: list[Callable[[Any, Any], None]] = []

    def produce(self, **kwargs: Any) -> None:
        self.produced.append(kwargs)
        self._pending.append(kwargs["on_delivery"])

    def flush(self, timeout: Optional[float] = None) -> int:
        pending, self._pending = self._pending, []
        for callback in pending:
            callback(self.delivery_error, None)
        return 0

    def poll(self, timeout: float) -> int:
        return 0


class DrainDlqTest(TestCase):
    def _drain(
        self,
        batches: list[list[FakeMessage]],
        producer: FakeProducer,
        consumer: Optional[FakeConsumer] = None,
        **kwargs: Any,
    ) -> tuple[dict[str, int], FakeConsumer]:
        consumer = consumer or FakeConsumer(batches)
        with (
            patch("posthog.kafka_client.dlq_replay.Consumer", return_value=consumer),
            patch("posthog.kafka_client.dlq_replay.Producer", return_value=producer),
            patch(
                "posthog.kafka_client.dlq_replay.get_profile_settings",
                return_value=SimpleNamespace(
                    hosts=["localhost:9092"],
                    security_protocol="PLAINTEXT",
                    sasl_mechanism=None,
                    sasl_user=None,
                    sasl_password=None,
                ),
            ),
        ):
            result = drain_dlq(
                source_topic="topic-dlq",
                target_topic="topic",
                group_id="dlq-replay-test",
                log=lambda _message: None,
                **kwargs,
            )
        return result, consumer

    def test_commits_once_per_delivered_batch(self) -> None:
        producer = FakeProducer()
        batch = [FakeMessage(b"one", [("error_name", b"ValueError")]), FakeMessage(b"two")]

        result, consumer = self._drain([batch], producer)

        assert result == {"replayed": 2, "exhausted": 0, "skipped": 0, "errors": 0}
        assert consumer.commits == 1
        assert [record["value"] for record in producer.produced] == [b"one", b"two"]
        assert dict(producer.produced[0]["headers"]) == {REPLAY_COUNT_HEADER: b"1"}

    def test_delivery_failure_is_reported_and_not_committed(self) -> None:
        producer = FakeProducer(delivery_error="Broker: Message too large")

        result, consumer = self._drain([[FakeMessage(b"one")]], producer)

        assert result == {"replayed": 0, "exhausted": 0, "skipped": 0, "errors": 1}
        assert consumer.commits == 0

    def test_batch_of_exhausted_messages_still_commits(self) -> None:
        producer = FakeProducer()
        at_cap = [(REPLAY_COUNT_HEADER, b"2")]

        result, consumer = self._drain([[FakeMessage(b"one", at_cap), FakeMessage(b"two", at_cap)]], producer)

        assert result == {"replayed": 0, "exhausted": 2, "skipped": 0, "errors": 0}
        assert consumer.commits == 1
        assert producer.produced == []

    def test_dry_run_counts_without_producing_or_committing(self) -> None:
        producer = FakeProducer()

        result, consumer = self._drain([[FakeMessage(b"one")]], producer, dry_run=True)

        assert result == {"replayed": 1, "exhausted": 0, "skipped": 0, "errors": 0}
        assert consumer.commits == 0
        assert producer.produced == []

    def test_skips_configured_team_ids_without_producing_but_still_commits(self) -> None:
        producer = FakeProducer()
        batch = [
            FakeMessage(b"keep", [("team_id", b"1")]),
            FakeMessage(b"drop", [("team_id", b"2")]),
        ]

        result, consumer = self._drain([batch], producer, skip_team_ids=frozenset({2}))

        assert result == {"replayed": 1, "exhausted": 0, "skipped": 1, "errors": 0}
        assert consumer.commits == 1
        assert [record["value"] for record in producer.produced] == [b"keep"]

    def test_stop_exits_after_committing_the_current_batch(self) -> None:
        producer = FakeProducer()
        calls = {"n": 0}

        def should_stop() -> bool:
            calls["n"] += 1
            return calls["n"] >= 2

        result, consumer = self._drain(
            [[FakeMessage(b"first")], [FakeMessage(b"second")]], producer, should_stop=should_stop
        )

        assert result["replayed"] == 1
        assert consumer.commits == 1
        assert [record["value"] for record in producer.produced] == [b"first"]

    @parameterized.expand(
        [
            ("waits_out_the_join_rebalance", [[], [], [FakeMessage(b"one")]], [[], [], ["tp"], ["tp"]], 60.0, 1),
            ("gives_up_when_never_assigned", [], [], 0.0, 0),
        ]
    )
    def test_empty_polls_without_an_assignment(
        self,
        _name: str,
        batches: list[list[FakeMessage]],
        assignments: list[list[str]],
        unassigned_timeout_seconds: float,
        expected_replayed: int,
    ) -> None:
        producer = FakeProducer()
        consumer = FakeConsumer(batches=batches, assignments=assignments)

        result, _ = self._drain(
            [],
            producer,
            consumer=consumer,
            idle_polls=2,
            unassigned_timeout_seconds=unassigned_timeout_seconds,
        )

        assert result["replayed"] == expected_replayed

    @parameterized.expand(
        [
            ("rebalance_keeps_going", REBALANCE_IN_PROGRESS, 0, [b"one", b"two"]),
            ("other_failure_stops_the_run", TIMED_OUT, 1, [b"one"]),
        ]
    )
    def test_commit_failure(self, _name: str, code: int, expected_errors: int, expected_produced: list[bytes]) -> None:
        producer = FakeProducer()
        consumer = FakeConsumer(
            [[FakeMessage(b"one")], [FakeMessage(b"two")]],
            commit_error=KafkaException(KafkaError(code)),
        )

        result, _ = self._drain([], producer, consumer=consumer)

        assert result["errors"] == expected_errors
        assert [record["value"] for record in producer.produced] == expected_produced


class SleepUntilTest(TestCase):
    def test_stops_sleeping_once_a_stop_is_requested(self) -> None:
        calls = {"n": 0}

        def should_stop() -> bool:
            calls["n"] += 1
            return calls["n"] > 2

        with patch("posthog.kafka_client.dlq_replay.time.sleep") as sleep:
            _sleep_until(time.monotonic() + 30.0, should_stop, slice_seconds=0.01)

        assert sleep.call_count == 2


class ThrottleDelayTest(TestCase):
    @parameterized.expand(
        [
            ("no_limit", 10, None, 0.5, 0.0),
            ("nothing_produced", 0, 100.0, 0.0, 0.0),
            ("already_slower_than_budget", 10, 100.0, 0.5, 0.0),
            ("needs_to_wait", 10, 100.0, 0.02, 0.08),
        ]
    )
    def test_throttle_delay(
        self, _name: str, produced: int, rate: Optional[float], elapsed: float, expected: float
    ) -> None:
        self.assertAlmostEqual(_throttle_delay(produced, rate, elapsed), expected, places=6)
