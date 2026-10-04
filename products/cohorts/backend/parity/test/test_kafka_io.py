from datetime import UTC, datetime

from unittest import mock

from django.test import SimpleTestCase

from confluent_kafka import TopicPartition

from products.cohorts.backend.parity.kafka_io import DrainStats, drain_topic

SINCE = datetime(2026, 7, 7, 19, 0, tzinfo=UTC)
TOPIC = "shadow-test"


class _FakeMessage:
    def __init__(self, partition: int, offset: int, ts: datetime, payload: bytes = b'{"n": 1}'):
        self._partition = partition
        self._offset = offset
        self._ts_ms = int(ts.timestamp() * 1000)
        self._payload = payload

    def error(self):
        return None

    def partition(self) -> int:
        return self._partition

    def offset(self) -> int:
        return self._offset

    def timestamp(self) -> tuple[int, int]:
        return (1, self._ts_ms)

    def value(self) -> bytes:
        return self._payload


class _FakeConsumer:
    def __init__(self, *, watermarks: dict[int, tuple[int, int]], starts: dict[int, int], polls: list[_FakeMessage]):
        self._watermarks = watermarks
        self._starts = starts
        self._polls = list(polls)
        self.assigned: list[TopicPartition] = []
        self.closed = False

    def list_topics(self, topic: str, timeout: float):
        topic_meta = mock.Mock(error=None, partitions=dict.fromkeys(self._watermarks))
        return mock.Mock(topics={topic: topic_meta})

    def get_watermark_offsets(self, tp: TopicPartition, timeout: float) -> tuple[int, int]:
        return self._watermarks[tp.partition]

    def offsets_for_times(self, tps: list[TopicPartition], timeout: float) -> list[TopicPartition]:
        return [TopicPartition(tp.topic, tp.partition, self._starts[tp.partition]) for tp in tps]

    def assign(self, assignment: list[TopicPartition]) -> None:
        self.assigned = assignment

    def poll(self, timeout: float):
        return self._polls.pop(0) if self._polls else None

    def close(self) -> None:
        self.closed = True


def _drain(consumer: _FakeConsumer, stats: DrainStats) -> list[dict]:
    with mock.patch("products.cohorts.backend.parity.kafka_io.Consumer", return_value=consumer):
        return list(drain_topic(TOPIC, config={}, since=SINCE, stats=stats))


class TestDrainTopic(SimpleTestCase):
    def test_fast_partition_stops_at_its_high_watermark_snapshot(self) -> None:
        ts = datetime(2026, 7, 7, 20, 0, tzinfo=UTC)
        consumer = _FakeConsumer(
            watermarks={0: (0, 1), 1: (0, 2)},
            starts={0: 0, 1: 0},
            polls=[
                _FakeMessage(0, 0, ts, b'{"p": "0-0"}'),
                # Produced after the snapshot on the already-finished partition 0: a
                # still-producing topic keeps returning these while partition 1 drains.
                _FakeMessage(0, 1, ts, b'{"p": "0-1-post-snapshot"}'),
                _FakeMessage(1, 0, ts, b'{"p": "1-0"}'),
                _FakeMessage(1, 1, ts, b'{"p": "1-1"}'),
            ],
        )
        stats = DrainStats()
        drained = _drain(consumer, stats)
        self.assertEqual([m["p"] for m in drained], ["0-0", "1-0", "1-1"])
        self.assertEqual(stats.consumed, 3)
        self.assertTrue(stats.reached_end)
        self.assertTrue(consumer.closed)

    def test_clipped_partition_sets_warning_stats(self) -> None:
        first_retained_ts = datetime(2026, 7, 7, 21, 0, tzinfo=UTC)
        consumer = _FakeConsumer(
            # low > 0: retention already deleted offsets, and the drain starts at low.
            watermarks={0: (5, 7)},
            starts={0: 5},
            polls=[_FakeMessage(0, 5, first_retained_ts), _FakeMessage(0, 6, first_retained_ts)],
        )
        stats = DrainStats()
        drained = _drain(consumer, stats)
        self.assertEqual(len(drained), 2)
        self.assertEqual(stats.earliest_retained, first_retained_ts)
        self.assertEqual(stats.maybe_clipped_partitions, [0])
        self.assertTrue(stats.reached_end)

    def test_empty_and_post_since_partitions_are_skipped(self) -> None:
        consumer = _FakeConsumer(
            # Partition 0 is empty; partition 1 has data but nothing at/after --since
            # (offsets_for_times returns -1).
            watermarks={0: (0, 0), 1: (0, 3)},
            starts={1: -1},
            polls=[],
        )
        stats = DrainStats()
        drained = _drain(consumer, stats)
        self.assertEqual(drained, [])
        self.assertEqual(stats.partitions, 2)
        self.assertEqual(stats.partitions_read, 0)
        self.assertTrue(stats.reached_end)

    def test_poll_timeout_leaves_reached_end_unset(self) -> None:
        consumer = _FakeConsumer(
            watermarks={0: (0, 2)},
            starts={0: 0},
            polls=[_FakeMessage(0, 0, datetime(2026, 7, 7, 20, 0, tzinfo=UTC))],
        )
        stats = DrainStats()
        drained = _drain(consumer, stats)
        self.assertEqual(len(drained), 1)
        self.assertFalse(stats.reached_end)
