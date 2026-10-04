from datetime import date

import pytest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.data_warehouse.backend.logic.backfill_status import describe_partition_key, historical_backfill_months
from products.data_warehouse.backend.models import ManagedWarehouseBackfillPartition

Granularity = ManagedWarehouseBackfillPartition.Granularity


class TestDescribePartitionKey(SimpleTestCase):
    @parameterized.expand(
        [
            ("historical_month", "1_2026-05", Granularity.MONTH, date(2026, 5, 1)),
            ("single_day", "1_2026-05-04", Granularity.DAY, date(2026, 5, 4)),
            ("persons_full_export", "42", Granularity.FULL, None),
            ("multi_digit_team", "123456_2026-11", Granularity.MONTH, date(2026, 11, 1)),
        ]
    )
    def test_decodes_the_period_a_key_covers(
        self, _name: str, partition_key: str, expected_granularity: str, expected_period_start: date | None
    ) -> None:
        descriptor = describe_partition_key(partition_key)

        assert descriptor.granularity == expected_granularity
        assert descriptor.period_start == expected_period_start

    @parameterized.expand(
        [
            ("no_period", "1_2026"),
            ("not_a_key", "team-one"),
            ("impossible_date", "1_2026-13-01"),
            ("empty", ""),
        ]
    )
    def test_rejects_a_key_it_cannot_decode(self, _name: str, partition_key: str) -> None:
        with pytest.raises(ValueError):
            describe_partition_key(partition_key)


class TestHistoricalBackfillMonths(SimpleTestCase):
    def test_stops_at_the_last_complete_month(self) -> None:
        # The current month belongs to the daily backfill, so history must exclude it — counting it
        # would leave the UI permanently one partition short of complete.
        months = historical_backfill_months(date(2026, 3, 14), today=date(2026, 7, 13))

        assert months == ["2026-03", "2026-04", "2026-05", "2026-06"]

    def test_is_empty_when_the_first_event_is_this_month(self) -> None:
        assert historical_backfill_months(date(2026, 7, 2), today=date(2026, 7, 13)) == []
