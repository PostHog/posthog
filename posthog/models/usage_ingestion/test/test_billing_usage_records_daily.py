from datetime import UTC, datetime, timedelta
from uuid import UUID

from posthog.test.base import ClickhouseTestMixin

from django.test import SimpleTestCase

from posthog.clickhouse.client import sync_execute
from posthog.models.usage_ingestion.billing_usage_records import (
    BASE_BILLING_USAGE_RECORDS_COLUMNS,
    BILLING_USAGE_RECORDS_DAILY_DATA_TABLE_SQL,
    BILLING_USAGE_RECORDS_DAILY_ROLLUP_SQL,
)

SOURCE_TABLE = "test_billing_usage_records_daily_source"
TARGET_TABLE = "test_billing_usage_records_daily_target"
TEAM_ID = 9_999_998
ORGANIZATION_ID = UUID("00000000-0000-0000-0000-000000000001")
DAY_START = datetime(2026, 5, 5, tzinfo=UTC)


class TestBillingUsageRecordsDaily(ClickhouseTestMixin, SimpleTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        sync_execute(
            f"""
            CREATE TABLE IF NOT EXISTS {SOURCE_TABLE}
            ({BASE_BILLING_USAGE_RECORDS_COLUMNS})
            ENGINE = ReplacingMergeTree(inserted_at)
            ORDER BY (team_id, toDate(timestamp), producer_id, usage_key, record_id)
            """
        )
        sync_execute(BILLING_USAGE_RECORDS_DAILY_DATA_TABLE_SQL(TARGET_TABLE))

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            sync_execute(f"DROP TABLE IF EXISTS {SOURCE_TABLE}")
            sync_execute(f"DROP TABLE IF EXISTS {TARGET_TABLE} SYNC")
        finally:
            super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        sync_execute(f"TRUNCATE TABLE {SOURCE_TABLE}")
        sync_execute(f"TRUNCATE TABLE {TARGET_TABLE}")

    def _rollup(self, rolled_up_at: datetime) -> None:
        sync_execute(
            BILLING_USAGE_RECORDS_DAILY_ROLLUP_SQL(SOURCE_TABLE, TARGET_TABLE),
            {
                "day_start": DAY_START,
                "day_end": DAY_START + timedelta(days=1),
                "rolled_up_at": rolled_up_at,
            },
        )

    def _daily_totals(self) -> list[tuple[str, int]]:
        return sync_execute(
            f"""
            SELECT usage_key, argMax(quantity, rolled_up_at)
            FROM {TARGET_TABLE}
            WHERE team_id = %(team_id)s AND day = toDate(%(day)s)
            GROUP BY usage_key
            ORDER BY usage_key
            """,
            {"team_id": TEAM_ID, "day": DAY_START},
        )

    def test_rollup_deduplicates_corrections_and_replaces_a_rerun(self) -> None:
        rows = [
            {
                "schema_version": 1,
                "record_id": "corrected",
                "producer_id": "test-producer",
                "team_id": TEAM_ID,
                "organization_id": ORGANIZATION_ID,
                "usage_key": "events",
                "unit": "events",
                "quantity": 10,
                "timestamp": DAY_START + timedelta(hours=1),
                "inserted_at": DAY_START + timedelta(hours=1),
            },
            {
                "schema_version": 1,
                "record_id": "corrected",
                "producer_id": "test-producer",
                "team_id": TEAM_ID,
                "organization_id": ORGANIZATION_ID,
                "usage_key": "events",
                "unit": "events",
                "quantity": 12,
                "timestamp": DAY_START + timedelta(hours=1),
                "inserted_at": DAY_START + timedelta(hours=2),
            },
            {
                "schema_version": 1,
                "record_id": "second-record",
                "producer_id": "test-producer",
                "team_id": TEAM_ID,
                "organization_id": ORGANIZATION_ID,
                "usage_key": "events",
                "unit": "events",
                "quantity": 4,
                "timestamp": DAY_START + timedelta(hours=3),
                "inserted_at": DAY_START + timedelta(hours=3),
            },
            {
                "schema_version": 1,
                "record_id": "other-key",
                "producer_id": "test-producer",
                "team_id": TEAM_ID,
                "organization_id": ORGANIZATION_ID,
                "usage_key": "recordings",
                "unit": "seconds",
                "quantity": 5,
                "timestamp": DAY_START + timedelta(hours=4),
                "inserted_at": DAY_START + timedelta(hours=4),
            },
        ]
        sync_execute(f"INSERT INTO {SOURCE_TABLE} VALUES", rows)

        self._rollup(DAY_START + timedelta(days=1))
        self.assertEqual(self._daily_totals(), [("events", 16), ("recordings", 5)])

        rows[1]["quantity"] = 15
        rows[1]["inserted_at"] = DAY_START + timedelta(hours=5)
        sync_execute(f"INSERT INTO {SOURCE_TABLE} VALUES", [rows[1]])

        self._rollup(DAY_START + timedelta(days=2))
        self.assertEqual(self._daily_totals(), [("events", 19), ("recordings", 5)])
