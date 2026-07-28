"""End-to-end test that produces events to the dedicated usage-report-preagg Kafka
table and verifies the usage_report_events_preagg materialized view aggregates them correctly.
Mirrors the test_kafka_insert pattern in ee/clickhouse/models/test/test_dead_letter_queue.py.

Requires a running Kafka broker reachable via settings.KAFKA_PROFILES["default"].
"""

import json
import time
import contextlib
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.conf import settings

from kafka import KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import KafkaError, TopicAlreadyExistsError

from posthog.clickhouse.client import sync_execute
from posthog.models.usage_report_events_preagg.sql import (
    DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
    KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE,
    KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
    SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE,
    SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
    USAGE_REPORT_EVENTS_PREAGG_MV,
    USAGE_REPORT_EVENTS_PREAGG_MV_SQL,
    USAGE_REPORT_EVENTS_PREAGG_TABLE,
    WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE,
    WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
)

# Own topic per run rather than the shared events topic, so the MV only ever sees rows this
# test produced and its consumer never has to read past anything else to find them.
TEST_TOPIC = f"test_usage_report_events_preagg_{uuid4().hex}"

# team_ids picked far above any realistic seeded test team, one per test — the MV writes
# asynchronously, so rows one test produced can still be landing while another polls.
READINESS_TEAM_ID = 9_999_997
FLOW_TEAM_ID = 9_999_998
REPLAY_TEAM_ID = 9_999_999
TEST_DATE = "2026-05-05"
TEST_EVENT_DAY_TIMESTAMP = f"{TEST_DATE} 12:34:56"

# Once the consumer is live, a produced message is only visible after the MV's next block
# flush — `kafka_flush_interval_ms` defaults to 7.5s, so allow a few of those.
POLL_TIMEOUT_SECONDS = 30

# Joining the consumer group and getting a partition assignment is a one-off cost paid
# before any test runs, and it can take longer than a flush interval on its own.
CONSUMER_READY_TIMEOUT_SECONDS = 90


def _make_event_payload(team_id: int, distinct_id: str, event: str, lib: str = "web") -> dict[str, Any]:
    """Build a minimal event payload that satisfies the dedicated kafka_usage_report_events_preagg JSONEachRow schema."""
    return {
        "uuid": str(uuid4()),
        "event": event,
        "properties": json.dumps({"$lib": lib}),
        "timestamp": TEST_EVENT_DAY_TIMESTAMP,
        "team_id": team_id,
        "distinct_id": distinct_id,
        "person_mode": "full",
    }


def _wait_for_team_row(
    team_id: int, expected_unique: int, expected_total: int, timeout_seconds: int = POLL_TIMEOUT_SECONDS
) -> tuple[int, int]:
    """Poll usage_report_events_preagg until BOTH uniqExactMerge >= expected_unique AND
    sumMerge >= expected_total. Both conditions are required because in a replay scenario
    `unique_count` saturates at 1 after the first message lands while `total_count` is
    still climbing — returning early on `unique_count` alone races the second message.

    Returns (unique_count, total_count) once both observed, or raises AssertionError on timeout.
    """
    deadline = time.monotonic() + timeout_seconds
    last_seen: tuple[int, int] = (0, 0)
    while time.monotonic() < deadline:
        result = sync_execute(
            f"""
            SELECT
                uniqExactMerge(distinct_events_unique) AS unique_count,
                toInt64(sumMerge(event_count)) AS total_count
            FROM {USAGE_REPORT_EVENTS_PREAGG_TABLE}
            WHERE team_id = %(team_id)s AND date = toDate(%(date)s)
            """,
            {"team_id": team_id, "date": TEST_DATE},
        )
        last_seen = (int(result[0][0] or 0), int(result[0][1] or 0))
        if last_seen[0] >= expected_unique and last_seen[1] >= expected_total:
            return last_seen
        time.sleep(0.5)
    raise AssertionError(
        f"usage_report_events_preagg never reached unique>={expected_unique}, total>={expected_total} "
        f"for team {team_id}; last seen {last_seen}"
    )


@contextlib.contextmanager
def _kafka_admin() -> Iterator[KafkaAdminClient]:
    admin = KafkaAdminClient(bootstrap_servers=settings.KAFKA_PROFILES["default"].hosts)
    try:
        yield admin
    finally:
        admin.close()


class TestUsageReportEventsPreaggMV(ClickhouseTestMixin, BaseTest):
    producer: KafkaProducer

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        try:
            cls._start_consuming()
        except Exception:
            # unittest skips tearDownClass when setUpClass raises, and Django only rolls its
            # class-level atomic block back there — leaving it open would break every test
            # class that runs after this one.
            cls.tearDownClass()
            raise

    @classmethod
    def _start_consuming(cls) -> None:
        # Create the topic before the Kafka table subscribes to it: librdkafka backs its
        # metadata refresh off after an UNKNOWN_TOPIC response, which costs seconds before
        # the consumer sees anything at all.
        with _kafka_admin() as admin, contextlib.suppress(TopicAlreadyExistsError):
            admin.create_topics([NewTopic(name=TEST_TOPIC, num_partitions=1, replication_factor=1)])

        cls.producer = KafkaProducer(bootstrap_servers=settings.KAFKA_PROFILES["default"].hosts)

        # Kafka table and MV live for the whole class. Recreating them per test made every
        # test after the first pay another consumer-group join before it could see a row.
        sync_execute(SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL())
        # The table normally goes away in tearDownClass; truncate in case a crashed earlier
        # run left rows behind for these team_ids.
        sync_execute(f"TRUNCATE TABLE IF EXISTS {SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE}")
        sync_execute(DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL())
        sync_execute(WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL())
        sync_execute(KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL(topic=TEST_TOPIC))
        sync_execute(USAGE_REPORT_EVENTS_PREAGG_MV_SQL())

        # Block until the consumer demonstrably delivers, so the tests themselves never have
        # to absorb the one-off join latency.
        cls._produce(_make_event_payload(READINESS_TEAM_ID, "user_ready", event="readiness"))
        _wait_for_team_row(
            READINESS_TEAM_ID,
            expected_unique=1,
            expected_total=1,
            timeout_seconds=CONSUMER_READY_TIMEOUT_SECONDS,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        # Tolerant of partial setup — setUpClass calls this to unwind a failed start.
        producer = getattr(cls, "producer", None)
        if producer is not None:
            producer.close()

        sync_execute(f"DROP TABLE IF EXISTS {USAGE_REPORT_EVENTS_PREAGG_MV}")
        sync_execute(f"DROP TABLE IF EXISTS {KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE}")
        sync_execute(f"DROP TABLE IF EXISTS {WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE}")
        sync_execute(f"DROP TABLE IF EXISTS {USAGE_REPORT_EVENTS_PREAGG_TABLE}")
        sync_execute(f"DROP TABLE IF EXISTS {SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE} SYNC")

        # Best effort — a leftover topic on an ephemeral CI broker is harmless, but repeated
        # local runs would otherwise pile them up.
        with contextlib.suppress(KafkaError), _kafka_admin() as admin:
            admin.delete_topics([TEST_TOPIC])

        super().tearDownClass()

    @classmethod
    def _produce(cls, *payloads: dict[str, Any]) -> None:
        for payload in payloads:
            cls.producer.send(topic=TEST_TOPIC, value=json.dumps(payload).encode("utf-8"))
        cls.producer.flush()

    def test_kafka_event_flows_into_aggregate(self) -> None:
        """Two events with distinct uuids land as 2 unique billable events in the daily agg."""
        self._produce(
            _make_event_payload(FLOW_TEAM_ID, "user_a", event="pageview"),
            _make_event_payload(FLOW_TEAM_ID, "user_b", event="pageview"),
        )

        unique_count, total_count = _wait_for_team_row(FLOW_TEAM_ID, expected_unique=2, expected_total=2)
        self.assertEqual(unique_count, 2)
        self.assertEqual(total_count, 2)

        # Verify the MV's grouping columns are populated correctly.
        rows = sync_execute(
            f"""
            SELECT date, team_id, person_mode, lib, event
            FROM {USAGE_REPORT_EVENTS_PREAGG_TABLE}
            WHERE team_id = %(team_id)s AND date = toDate(%(date)s)
            GROUP BY date, team_id, person_mode, lib, event
            """,
            {"team_id": FLOW_TEAM_ID, "date": TEST_DATE},
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row[0], datetime.strptime(TEST_DATE, "%Y-%m-%d").date())
        self.assertEqual(row[1], FLOW_TEAM_ID)
        self.assertEqual(row[2], "full")
        self.assertEqual(row[3], "web")
        self.assertEqual(row[4], "pageview")

    def test_kafka_replayed_event_dedupes(self) -> None:
        """Sending the same (distinct_id, uuid) pair twice yields 1 unique billable event but 2 in raw count."""
        # Ship the same payload twice — same uuid, same distinct_id.
        payload = _make_event_payload(REPLAY_TEAM_ID, "user_replay", event="pageview")
        self._produce(payload, payload)

        unique_count, total_count = _wait_for_team_row(REPLAY_TEAM_ID, expected_unique=1, expected_total=2)
        self.assertEqual(unique_count, 1, "uniqExactMerge should dedupe identical (distinct_id, uuid, event) tuples")
        # event_count sums every row including replays, and Kafka delivery is at-least-once,
        # so 2 is the floor rather than an exact expectation.
        self.assertGreaterEqual(total_count, 2)
