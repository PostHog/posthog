import io
import datetime as dt

import pytest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import CLICKHOUSE_BATCH_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import health_check_class_for_kind
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.registry import HEALTH_CHECKS, ensure_registry_loaded
from posthog.temporal.health_checks.rollups.checks import RollupHealthCheck, compare_issues
from posthog.temporal.health_checks.rollups.fill import DayFill, _copy_text, team_id_ranges
from posthog.temporal.health_checks.rollups.freshness import window_from_published_days
from posthog.temporal.health_checks.rollups.runner import plan_requested_days, plan_scheduled_days
from posthog.temporal.health_checks.rollups.store import DayStats
from posthog.temporal.health_checks.rollups.validation import day_moved, refusal_reason

from products.growth.backend.sdk_version_rollup import SdkVersionsDailyRollup

TODAY = dt.date(2026, 10, 29)


def _fill(row_count: int, event_count: int = 1000) -> DayFill:
    return DayFill(day=TODAY, row_count=row_count, event_count=event_count, buffer=io.BytesIO())


def _history(*row_counts: int) -> list[DayStats]:
    return [DayStats(row_count=rows, event_count=rows * 10) for rows in row_counts]


def _proxy_issue(*unproxied_hosts: str) -> HealthCheckResult:
    return HealthCheckResult(
        severity=HealthIssue.Severity.WARNING, payload={"unproxied_hosts": list(unproxied_hosts)}, hash_keys=[]
    )


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

    @parameterized.expand(
        [
            ("every_day_published", _days_back(*range(1, 11)), [(1, "publish"), (2, "refresh")]),
            (
                "gaps_inside_retention",
                _days_back(1, 2, 3, 5, 6, 7, 8, 9),
                [(1, "publish"), (2, "refresh"), (4, "publish"), (10, "publish")],
            ),
            (
                "first_run_after_deploy",
                [],
                [(1, "publish"), (2, "refresh"), *[(offset, "publish") for offset in range(3, 11)]],
            ),
        ]
    )
    def test_scheduled_plan_refreshes_recent_days_and_fills_every_missing_day_retention_keeps(
        self, _name: str, published: list[dt.date], expected: list[tuple[int, str]]
    ) -> None:
        plan = plan_scheduled_days(SdkVersionsDailyRollup, today=TODAY, published=published)

        assert [(step.day, step.mode) for step in plan] == [
            (TODAY - dt.timedelta(days=offset), mode) for offset, mode in expected
        ]

    def test_requested_plan_publishes_each_day_once_and_refuses_today(self) -> None:
        plan = plan_requested_days(_days_back(9, 10, 9), today=TODAY)
        assert [(step.day, step.mode) for step in plan] == [
            (dt.date(2026, 10, 19), "publish"),
            (dt.date(2026, 10, 20), "publish"),
        ]

        with pytest.raises(ValueError):
            plan_requested_days([TODAY], today=TODAY)

    def test_checks_not_reading_their_rollup_keep_clickhouse_sized_batches(self) -> None:
        ensure_registry_loaded()
        shadow_kinds = []
        for kind in HEALTH_CHECKS:
            check = health_check_class_for_kind(kind)
            if check is not None and issubclass(check, RollupHealthCheck) and not check.reads_rollup:
                shadow_kinds.append(kind)

        assert shadow_kinds
        for kind in shadow_kinds:
            assert HEALTH_CHECKS[kind].batch_size == CLICKHOUSE_BATCH_EXECUTION_POLICY.batch_size, kind

    @parameterized.expand(
        [
            ("same_issue", [_proxy_issue("a.example.com")], [_proxy_issue("a.example.com")], ["both_flagged"]),
            ("only_rollup", [_proxy_issue("a.example.com")], [], ["only_rollup"]),
            ("only_events", [], [_proxy_issue("a.example.com")], ["only_events"]),
            (
                "other_hosts",
                [_proxy_issue("a.example.com")],
                [_proxy_issue("b.example.com")],
                ["both_flagged", "different_payloads"],
            ),
        ]
    )
    def test_compare_issues_reports_each_kind_of_disagreement(
        self,
        _name: str,
        from_rollup: list[HealthCheckResult],
        from_events: list[HealthCheckResult],
        expected: list[str],
    ) -> None:
        comparison = compare_issues("partial_proxy", [1, 2], {1: from_rollup}, {1: from_events})

        found = {
            "both_flagged": comparison.both_flagged == 1,
            "only_rollup": comparison.only_rollup == [1],
            "only_events": comparison.only_events == [1],
            "different_payloads": comparison.different_payloads == [1],
        }
        assert [name for name, present in found.items() if present] == expected
        assert comparison.different_issues == []
