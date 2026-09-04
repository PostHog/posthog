"""Tests the usage_report_events_preagg materialized view projection: how raw event rows
aggregate into daily billable counts and which columns they group by.

The projection runs against a plain source table that stands in for the dedicated Kafka
engine table, so the test is deterministic. Live Kafka transport (the Kafka engine table
and the materialized view that binds to it) is exercised separately when migration 0251
runs against the test ClickHouse.
"""

import json
from datetime import datetime
from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin

from django.test import SimpleTestCase

from posthog.clickhouse.client import sync_execute
from posthog.models.usage_report_events_preagg.sql import (
    DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
    KAFKA_USAGE_REPORT_EVENTS_PREAGG_COLUMNS,
    SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE,
    SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
    USAGE_REPORT_EVENTS_PREAGG_MV_SELECT_SQL,
    USAGE_REPORT_EVENTS_PREAGG_TABLE,
    WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE,
    WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
)

# Team ids picked far above any realistic seeded test team keep each case isolated
# from the other case and from leftover data in the shared dev/test ClickHouse.
EVENT_FLOW_TEST_TEAM_ID = 9_999_999
REPLAY_TEST_TEAM_ID = 10_000_000
TEST_DATE = "2026-05-05"
TEST_EVENT_TIMESTAMP = datetime(2026, 5, 5, 12, 34, 56)

# Plain source table with the Kafka engine table's exact columns. The projection reads
# from here instead of Kafka, so aggregation is verified without a broker in the loop.
SOURCE_USAGE_REPORT_EVENTS_PREAGG_TABLE = "test_source_usage_report_events_preagg"


def _make_event_row(distinct_id: str, event: str, lib: str, team_id: int) -> dict:
    return {
        "uuid": str(uuid4()),
        "event": event,
        "properties": json.dumps({"$lib": lib}),
        "timestamp": TEST_EVENT_TIMESTAMP,
        "team_id": team_id,
        "distinct_id": distinct_id,
        "person_mode": "full",
    }


class TestUsageReportEventsPreaggMV(ClickhouseTestMixin, SimpleTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        sync_execute(SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL())
        sync_execute(DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL())
        sync_execute(WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL())
        sync_execute(
            f"""
            CREATE TABLE IF NOT EXISTS {SOURCE_USAGE_REPORT_EVENTS_PREAGG_TABLE}
            ({KAFKA_USAGE_REPORT_EVENTS_PREAGG_COLUMNS})
            ENGINE = MergeTree() ORDER BY (team_id, timestamp)
            """
        )

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            sync_execute(f"DROP TABLE IF EXISTS {SOURCE_USAGE_REPORT_EVENTS_PREAGG_TABLE}")
            sync_execute(f"DROP TABLE IF EXISTS {WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE}")
            sync_execute(f"DROP TABLE IF EXISTS {USAGE_REPORT_EVENTS_PREAGG_TABLE}")
            sync_execute(f"DROP TABLE IF EXISTS {SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE} SYNC")
        finally:
            super().tearDownClass()

    def _project_rows(self, rows: list[dict], team_id: int) -> None:
        """Insert raw event rows, then run the real MV projection into the writable table."""
        sync_execute(f"TRUNCATE TABLE {SOURCE_USAGE_REPORT_EVENTS_PREAGG_TABLE}")
        sync_execute(
            f"DELETE FROM {SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE} WHERE team_id = %(t)s",
            {"t": team_id},
        )
        sync_execute(
            f"""
            INSERT INTO {SOURCE_USAGE_REPORT_EVENTS_PREAGG_TABLE}
            (uuid, event, properties, timestamp, team_id, distinct_id, person_mode) VALUES
            """,
            rows,
        )
        sync_execute(
            f"INSERT INTO {WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE} "
            + USAGE_REPORT_EVENTS_PREAGG_MV_SELECT_SQL(SOURCE_USAGE_REPORT_EVENTS_PREAGG_TABLE)
        )

    def _read_counts(self, team_id: int) -> tuple[int, int]:
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
        return int(result[0][0] or 0), int(result[0][1] or 0)

    def test_projection_counts_unique_billable_events(self) -> None:
        """Two events with distinct uuids land as 2 unique billable events in the daily agg."""
        rows = [
            _make_event_row(distinct_id, event="pageview", lib="web", team_id=EVENT_FLOW_TEST_TEAM_ID)
            for distinct_id in ("user_a", "user_b")
        ]
        self._project_rows(rows, EVENT_FLOW_TEST_TEAM_ID)

        unique_count, total_count = self._read_counts(EVENT_FLOW_TEST_TEAM_ID)
        self.assertEqual(unique_count, 2)
        self.assertEqual(total_count, 2)

        # Verify the projection's grouping columns are populated correctly.
        grouped = sync_execute(
            f"""
            SELECT date, team_id, person_mode, lib, event
            FROM {USAGE_REPORT_EVENTS_PREAGG_TABLE}
            WHERE team_id = %(team_id)s AND date = toDate(%(date)s)
            GROUP BY date, team_id, person_mode, lib, event
            """,
            {"team_id": EVENT_FLOW_TEST_TEAM_ID, "date": TEST_DATE},
        )
        self.assertEqual(len(grouped), 1)
        row = grouped[0]
        self.assertEqual(row[0], datetime.strptime(TEST_DATE, "%Y-%m-%d").date())
        self.assertEqual(row[1], EVENT_FLOW_TEST_TEAM_ID)
        self.assertEqual(row[2], "full")
        self.assertEqual(row[3], "web")
        self.assertEqual(row[4], "pageview")

    def test_projection_dedupes_replayed_events(self) -> None:
        """The same (distinct_id, uuid, event) tuple twice yields 1 unique billable event but 2 in raw count."""
        row = _make_event_row("user_replay", event="pageview", lib="web", team_id=REPLAY_TEST_TEAM_ID)
        self._project_rows([row, dict(row)], REPLAY_TEST_TEAM_ID)

        unique_count, total_count = self._read_counts(REPLAY_TEST_TEAM_ID)
        self.assertEqual(unique_count, 1, "uniqExactMerge should dedupe identical (distinct_id, uuid, event) tuples")
        self.assertEqual(total_count, 2, "event_count sums every row, including replays")
