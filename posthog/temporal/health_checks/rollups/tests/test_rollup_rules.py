import io
import datetime as dt

import pytest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.temporal.health_checks.rollups.activities import build_plan
from posthog.temporal.health_checks.rollups.fill import DayFill, _copy_text, team_id_ranges
from posthog.temporal.health_checks.rollups.freshness import window_from_published_days
from posthog.temporal.health_checks.rollups.inputs import DailyRollupWorkflowInputs
from posthog.temporal.health_checks.rollups.store import DayStats
from posthog.temporal.health_checks.rollups.validation import day_moved, refusal_reason

from products.growth.backend.temporal.rollups.sdk_versions import SdkVersionsDailyRollup

TODAY = dt.date(2026, 10, 29)


def _fill(row_count: int, event_count: int = 1000) -> DayFill:
    return DayFill(day=TODAY, row_count=row_count, event_count=event_count, buffer=io.BytesIO())


def _history(*row_counts: int) -> list[DayStats]:
    return [DayStats(row_count=rows, event_count=rows * 10) for rows in row_counts]


def _days_back(*offsets: int) -> list[dt.date]:
    return [TODAY - dt.timedelta(days=offset) for offset in offsets]


class TestRollupRules(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty", [], 16, 0),
            ("fewer_teams_than_ranges", [5, 9, 2], 16, 3),
            ("many_teams", list(range(1, 1001)), 16, 16),
            ("sparse_ids_with_duplicates", [1, 1, 50, 9_000, 9_001, 500_000], 4, 4),
        ]
    )
    def test_team_id_ranges_cover_every_team_exactly_once(
        self, _name: str, team_ids: list[int], count: int, expected_ranges: int
    ) -> None:
        ranges = team_id_ranges(team_ids, count)

        assert len(ranges) == expected_ranges
        for team_id in set(team_ids):
            assert sum(r.start <= team_id < r.end for r in ranges) == 1

    @parameterized.expand(
        [
            ("null", None, "\\N"),
            ("true", True, "t"),
            ("false", False, "f"),
            ("int", 42, "42"),
            ("date", dt.date(2026, 10, 22), "2026-10-22"),
            ("naive_datetime_is_utc", dt.datetime(2026, 10, 22, 23, 59, 41), "2026-10-22T23:59:41+00:00"),
            ("tab_newline_backslash", "1.0\t\n\r\\x", "1.0\\t\\n\\r\\\\x"),
        ]
    )
    def test_copy_text_formats_values_for_postgres(self, _name: str, value: object, expected: str) -> None:
        assert _copy_text(value) == expected

    def test_copy_text_rejects_nul(self) -> None:
        with pytest.raises(ValueError):
            _copy_text("1.0\x00")

    @parameterized.expand(
        [
            ("empty_day", 0, _history(100, 100, 100), False, "no rows"),
            ("empty_day_even_when_forced", 0, _history(100, 100, 100), True, "no rows"),
            ("over_cap_even_when_forced", SdkVersionsDailyRollup.max_rows_per_day + 1, [], True, "more than"),
            ("under_half_the_median", 40, _history(100, 90, 110), False, "median"),
            ("under_half_the_median_but_forced", 40, _history(100, 90, 110), True, None),
            ("normal_day", 95, _history(100, 90, 110), False, None),
            ("too_little_history_for_a_median", 1, _history(100, 100), False, None),
        ]
    )
    def test_refusal_reason(
        self, _name: str, row_count: int, history: list[DayStats], force: bool, expected: str | None
    ) -> None:
        reason = refusal_reason(SdkVersionsDailyRollup, _fill(row_count), history, force=force)

        if expected is None:
            assert reason is None
        else:
            assert reason is not None and expected in reason

    @parameterized.expand(
        [
            ("never_published", None, 100, 1000, True),
            ("identical", DayStats(row_count=100, event_count=1000), 100, 1000, False),
            ("within_one_percent", DayStats(row_count=100, event_count=1000), 101, 1010, False),
            ("late_events", DayStats(row_count=100, event_count=1000), 100, 1011, True),
            ("new_rows", DayStats(row_count=100, event_count=1000), 102, 1000, True),
        ]
    )
    def test_day_moved(self, _name: str, published: DayStats | None, rows: int, events: int, expected: bool) -> None:
        assert day_moved(published, _fill(rows, events)) is expected

    @parameterized.expand(
        [
            ("full_window", _days_back(*range(1, 8)), 7, (TODAY - dt.timedelta(days=7), TODAY - dt.timedelta(days=1))),
            (
                "latest_is_two_days_old",
                _days_back(*range(2, 9)),
                7,
                (TODAY - dt.timedelta(days=8), TODAY - dt.timedelta(days=2)),
            ),
            ("latest_is_three_days_old", _days_back(*range(3, 10)), 7, None),
            ("gap_inside_window", _days_back(1, 2, 3, 5, 6, 7, 8), 7, None),
            ("first_days_after_deploy", _days_back(1, 2, 3), 30, None),
            ("nothing_published", [], 7, None),
        ]
    )
    def test_window_from_published_days(
        self, _name: str, published: list[dt.date], days: int, expected: tuple[dt.date, dt.date] | None
    ) -> None:
        window = window_from_published_days(published, days, today=TODAY)

        assert (None if window is None else (window.start, window.end)) == expected

    def test_default_plan_publishes_yesterday_and_refreshes_the_day_before(self) -> None:
        plan = build_plan(DailyRollupWorkflowInputs(tables=[SdkVersionsDailyRollup.table()]), today=TODAY)

        assert [(step.day, step.mode) for step in plan.steps] == [("2026-10-28", "publish"), ("2026-10-27", "refresh")]
        assert plan.retention_tables == [SdkVersionsDailyRollup.table()]

    def test_backfill_plan_publishes_each_requested_day_and_refuses_today(self) -> None:
        table = SdkVersionsDailyRollup.table()
        plan = build_plan(DailyRollupWorkflowInputs(tables=[table], days=["2026-10-20", "2026-10-19"]), today=TODAY)
        assert [(step.day, step.mode) for step in plan.steps] == [("2026-10-19", "publish"), ("2026-10-20", "publish")]

        with pytest.raises(ValueError):
            build_plan(DailyRollupWorkflowInputs(tables=[table], days=[TODAY.isoformat()]), today=TODAY)
