import asyncio
from datetime import date

import pytest
from posthog.test.base import ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase

from temporalio.testing import ActivityEnvironment

from posthog.clickhouse.client import sync_execute
from posthog.models.usage_ingestion.billing_usage_records import (
    BASE_BILLING_USAGE_RECORDS_COLUMNS,
    BILLING_USAGE_RECORDS_HOURLY_DATA_TABLE_SQL,
    BILLING_USAGE_RECORDS_HOURLY_ROLLUP_SQL,
)
from posthog.temporal.billing_usage_rollup.activities import rollup_billing_usage_records
from posthog.temporal.billing_usage_rollup.types import BillingUsageRecordsRollupInput

SOURCE_TABLE = "test_billing_usage_records_rollup_activity_source"
TARGET_TABLE = "test_billing_usage_records_rollup_activity_target"
DAY = date(2026, 5, 5)
ROW_COUNT = 1_000_000


@pytest.mark.asyncio
async def test_rollup_activity_uses_the_requested_day() -> None:
    with patch("posthog.temporal.billing_usage_rollup.activities.rollup_billing_usage_records_day") as rollup:
        await ActivityEnvironment().run(rollup_billing_usage_records, BillingUsageRecordsRollupInput(day="2026-05-05"))

    rollup.assert_called_once_with(date(2026, 5, 5))


class TestRollupActivityStorage(ClickhouseTestMixin, SimpleTestCase):
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
        sync_execute(BILLING_USAGE_RECORDS_HOURLY_DATA_TABLE_SQL(TARGET_TABLE))

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

    def test_activity_rolls_up_a_large_source_table(self) -> None:
        sync_execute(
            f"""
            INSERT INTO {SOURCE_TABLE}
            SELECT
                1,
                concat('load-test-', toString(number)),
                concat('producer-', toString(intDiv(number, 100) % 4)),
                1 + (number % 100),
                toUUID(concat('00000000-0000-0000-0000-', leftPad(toString(1 + (number % 100)), 12, '0'))),
                concat('usage-', toString(intDiv(number, 400) % 4)),
                'units',
                1,
                toDateTime64('2026-05-05 00:00:00', 6, 'UTC') + toIntervalSecond(number % 86400),
                toDateTime64('2026-05-05 00:00:00', 6, 'UTC') + toIntervalDay(1)
            FROM numbers({ROW_COUNT})
            """
        )

        with patch(
            "posthog.temporal.billing_usage_rollup.activities.BILLING_USAGE_RECORDS_HOURLY_ROLLUP_SQL",
            return_value=BILLING_USAGE_RECORDS_HOURLY_ROLLUP_SQL(SOURCE_TABLE, TARGET_TABLE),
        ):
            asyncio.run(
                ActivityEnvironment().run(
                    rollup_billing_usage_records, BillingUsageRecordsRollupInput(day=DAY.isoformat())
                )
            )

        sync_execute(f"OPTIMIZE TABLE {SOURCE_TABLE} FINAL")
        sync_execute(f"OPTIMIZE TABLE {TARGET_TABLE} FINAL")
        source_rows, source_quantity, source_bytes = self._table_stats(SOURCE_TABLE)
        target_rows, target_quantity, target_bytes = self._table_stats(TARGET_TABLE)

        self.assertEqual(source_rows, ROW_COUNT)
        self.assertEqual(source_quantity, target_quantity)
        self.assertEqual(target_rows, 100 * 4 * 4 * 24)
        self.assertLess(target_rows, source_rows)
        self.assertLess(target_bytes, source_bytes)

    @staticmethod
    def _table_stats(table: str) -> tuple[int, int, int]:
        result = sync_execute(
            f"""
            SELECT count(), sum(quantity),
                (SELECT sum(bytes_on_disk) FROM system.parts WHERE active AND database = currentDatabase() AND table = '{table}')
            FROM {table}
            """
        )
        return result[0]
