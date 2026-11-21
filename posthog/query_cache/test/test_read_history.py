from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.query_cache.read_history import batched_reads, days_read_at_this_time, read_since, record_read

NOW = datetime(2026, 11, 10, 14, 20, tzinfo=UTC)


class TestReadHistory(BaseTest):
    @parameterized.expand(
        [
            ("same_hour_on_two_days", [timedelta(days=1), timedelta(days=3, minutes=15)], 2),
            ("next_hour_counts", [timedelta(days=2) - timedelta(hours=1)], 1),
            ("two_reads_on_one_day_count_once", [timedelta(days=1), timedelta(days=1) - timedelta(hours=1)], 1),
            ("earlier_in_the_day_does_not_count", [timedelta(days=1, hours=3)], 0),
            ("today_does_not_count", [timedelta(minutes=5)], 0),
            ("older_than_the_history_does_not_count", [timedelta(days=8)], 0),
        ]
    )
    def test_counts_days_with_a_read_at_this_time_of_day(self, _name: str, read_ages: list[timedelta], expected: int):
        for age in read_ages:
            record_read(team_id=self.team.pk, insight_id=7, dashboard_id=9, at=NOW - age)

        days = days_read_at_this_time(team_id=self.team.pk, identifiers=["7:9", "7:"], now=NOW)

        assert days == {"7:9": expected, "7:": 0}

    @parameterized.expand(
        [
            ("this_hour", timedelta(minutes=5), True),
            ("earlier_in_the_window", timedelta(hours=23), True),
            ("before_the_window", timedelta(hours=26), False),
        ]
    )
    def test_read_since_returns_identifiers_read_in_the_window(self, _name: str, age: timedelta, expected: bool):
        record_read(team_id=self.team.pk, insight_id=7, dashboard_id=9, at=NOW - age)

        read = read_since(team_id=self.team.pk, since=NOW - timedelta(hours=24), now=NOW)

        assert ("7:9" in read) is expected
        assert "7:" not in read

    def test_batched_reads_are_written_when_the_block_ends(self) -> None:
        since = NOW - timedelta(hours=24)

        with batched_reads():
            record_read(team_id=self.team.pk, insight_id=7, dashboard_id=9, at=NOW - timedelta(minutes=5))
            record_read(team_id=self.team.pk, insight_id=8, dashboard_id=9, at=NOW - timedelta(minutes=5))
            record_read(team_id=self.team.pk, insight_id=8, dashboard_id=None, at=NOW - timedelta(hours=3))
            assert read_since(team_id=self.team.pk, since=since, now=NOW) == set()

        assert read_since(team_id=self.team.pk, since=since, now=NOW) == {"7:9", "8:9", "8:"}

    def test_batched_reads_survive_a_failed_write(self) -> None:
        with patch("posthog.query_cache.read_history.redis.get_client", side_effect=ConnectionError("redis down")):
            with batched_reads():
                record_read(team_id=self.team.pk, insight_id=7, dashboard_id=9, at=NOW)
