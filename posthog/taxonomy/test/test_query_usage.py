from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.taxonomy.query_usage import query_usage_windows, summarize_query_usage

NEW_YORK = ZoneInfo("America/New_York")


class TestQueryUsageWindows(SimpleTestCase):
    def test_windows_follow_the_team_timezone_across_a_dst_change(self) -> None:
        # 01:30 UTC on March 20 is still March 19 in New York, and US clocks moved forward on March 8.
        windows = query_usage_windows(datetime(2026, 3, 20, 1, 30, tzinfo=UTC), NEW_YORK)

        assert windows.days[0] == date(2026, 2, 18)
        assert windows.days[-1] == date(2026, 3, 19)
        assert len(windows.days) == 30
        assert windows.current_start == datetime(2026, 2, 18, tzinfo=NEW_YORK)
        assert windows.current_start.astimezone(UTC) == datetime(2026, 2, 18, 5, tzinfo=UTC)
        assert windows.previous_start == datetime(2026, 1, 19, tzinfo=NEW_YORK)
        assert windows.previous_end.astimezone(UTC) == datetime(2026, 2, 18, 2, 30, tzinfo=UTC)
        assert windows.coverage_start == datetime(2026, 1, 12, tzinfo=NEW_YORK)


class TestSummarizeQueryUsage(SimpleTestCase):
    @parameterized.expand([["covered", True, 9], ["not covered", False, None]])
    def test_splits_days_into_windows_and_zero_fills(
        self, _name: str, previous_covered: bool, expected_previous: int | None
    ) -> None:
        windows = query_usage_windows(datetime(2026, 3, 20, 12, tzinfo=UTC), ZoneInfo("UTC"))

        usage = summarize_query_usage(
            [(date(2026, 2, 19), 4), (date(2026, 3, 20), 2), (date(2026, 3, 20), 1), (date(2026, 2, 18), 9)],
            windows,
            previous_covered,
        )

        assert usage.total == 7
        assert usage.previous_total == expected_previous
        assert [(day.date, day.count) for day in usage.daily if day.count] == [
            (date(2026, 2, 19), 4),
            (date(2026, 3, 20), 3),
        ]
        assert len(usage.daily) == 30
