"""End-to-end test that produces an event to the dedicated usage-report-preagg Kafka
table and verifies the usage_report_events_preagg materialized view aggregates it correctly.
Mirrors the test_kafka_insert pattern in ee/clickhouse/models/test/test_dead_letter_queue.py.

Requires a running Kafka broker reachable via settings.KAFKA_PROFILES["default"].
"""

import json
import time
from datetime import datetime
from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin

from django.conf import settings
from django.test import TestCase

from kafka import KafkaProducer

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON
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

# Team ids picked far above any realistic seeded test team keep each case isolated
# from the other case and from leftover data in the shared dev/test ClickHouse.
EVENT_FLOW_TEST_TEAM_ID = 9_999_999
REPLAY_TEST_TEAM_ID = 10_000_000
TEST_DATE = "2026-05-05"
TEST_EVENT_DAY_TIMESTAMP = f"{TEST_DATE} 12:34:56"


def _make_event_payload(distinct_id: str, event: str, lib: str, team_id: int) -> dict:
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
    team_id: int, expected_unique: int, expected_total: int, timeout_seconds: int = 90
) -> tuple[int, int]:
    """Poll usage_report_events_preagg until BOTH uniqExactMerge >= expected_unique AND
    sumMerge >= expected_total. Both conditions are required because in a replay scenario
    `unique_count` saturates at 1 after the first message lands while `total_count` is
    still climbing — returning early on `unique_count` alone races the second message.

    The timeout has to outlast the initial Kafka consumer startup and any broker rebalance.
    Polling stops as soon as both counts are satisfied, so a healthy run does not pay for
    this headroom.

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


class TestUsageReportEventsPreaggMV(ClickhouseTestMixin, TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        sync_execute(SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL())
        sync_execute(DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL())
        sync_execute(WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL())
        sync_execute(KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL())
        sync_execute(USAGE_REPORT_EVENTS_PREAGG_MV_SQL())

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            sync_execute(f"DROP TABLE IF EXISTS {USAGE_REPORT_EVENTS_PREAGG_MV}")
            sync_execute(f"DROP TABLE IF EXISTS {KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE}")
            sync_execute(f"DROP TABLE IF EXISTS {WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE}")
            sync_execute(f"DROP TABLE IF EXISTS {USAGE_REPORT_EVENTS_PREAGG_TABLE}")
            sync_execute(f"DROP TABLE IF EXISTS {SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE} SYNC")
        finally:
            super().tearDownClass()

    def test_kafka_event_flows_into_aggregate(self) -> None:
        """Two events with distinct uuids land as 2 unique billable events in the daily agg."""
        sync_execute(
            f"DELETE FROM {SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE} WHERE team_id = %(t)s",
            {"t": EVENT_FLOW_TEST_TEAM_ID},
        )
        producer = KafkaProducer(bootstrap_servers=settings.KAFKA_PROFILES["default"].hosts)
        for distinct_id in ("user_a", "user_b"):
            payload = _make_event_payload(distinct_id, event="pageview", lib="web", team_id=EVENT_FLOW_TEST_TEAM_ID)
            producer.send(topic=KAFKA_EVENTS_JSON, value=json.dumps(payload).encode("utf-8"))
        producer.flush()

        unique_count, total_count = _wait_for_team_row(EVENT_FLOW_TEST_TEAM_ID, expected_unique=2, expected_total=2)
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
            {"team_id": EVENT_FLOW_TEST_TEAM_ID, "date": TEST_DATE},
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row[0], datetime.strptime(TEST_DATE, "%Y-%m-%d").date())
        self.assertEqual(row[1], EVENT_FLOW_TEST_TEAM_ID)
        self.assertEqual(row[2], "full")
        self.assertEqual(row[3], "web")
        self.assertEqual(row[4], "pageview")

    def test_kafka_replayed_event_dedupes(self) -> None:
        """Sending the same (distinct_id, uuid) pair twice yields 1 unique billable event but 2 in raw count."""
        sync_execute(
            f"DELETE FROM {SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE} WHERE team_id = %(t)s",
            {"t": REPLAY_TEST_TEAM_ID},
        )
        producer = KafkaProducer(bootstrap_servers=settings.KAFKA_PROFILES["default"].hosts)
        payload = _make_event_payload("user_replay", event="pageview", lib="web", team_id=REPLAY_TEST_TEAM_ID)
        # Ship the same payload twice — same uuid, same distinct_id.
        for _ in range(2):
            producer.send(topic=KAFKA_EVENTS_JSON, value=json.dumps(payload).encode("utf-8"))
        producer.flush()

        unique_count, total_count = _wait_for_team_row(REPLAY_TEST_TEAM_ID, expected_unique=1, expected_total=2)
        self.assertEqual(unique_count, 1, "uniqExactMerge should dedupe identical (distinct_id, uuid, event) tuples")
        # event_count is summed across all rows including replays, so total_count
        # is at least 2. May be larger if the kafka consumer buffered earlier replays.
        self.assertGreaterEqual(total_count, 2)
