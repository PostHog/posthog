from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.data_quality.backend.facade.enums import CheckRunStatus, CheckType, SubjectStatus, SubjectType
from products.data_quality.backend.logic.scheduling import (
    SCAN_INTERVAL_SECONDS,
    advance_next_run_at,
    compute_shard_offset_seconds,
)
from products.data_quality.backend.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from products.data_quality.backend.temporal.activities.cleanup import (
    CHECK_RUN_RETENTION_DAYS,
    COMPILED_QUERY_RETENTION_DAYS,
    _cleanup,
)
from products.data_quality.backend.temporal.activities.schedule_due_checks import _retrieve_due_checks

NOW = datetime(2026, 7, 28, 12, 7, 30, tzinfo=UTC)


class TestSchedulingMath:
    @parameterized.expand(
        [
            ("never_run_lands_one_interval_out", None, 60, datetime(2026, 7, 28, 13, 0, tzinfo=UTC)),
            (
                "on_time_advances_one_interval",
                datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
                60,
                datetime(2026, 7, 28, 13, 0, tzinfo=UTC),
            ),
            (
                "a_day_of_downtime_does_not_backlog",
                datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
                60,
                datetime(2026, 7, 28, 13, 0, tzinfo=UTC),
            ),
        ]
    )
    def test_next_run_lands_on_the_cadence_grid_ahead_of_now(self, _name, current, interval, expected) -> None:
        assert advance_next_run_at(current, interval, NOW) == expected

    def test_a_missed_window_produces_one_run_not_many(self) -> None:
        # The point of skipping rather than catching up: a check disabled for a week must not
        # queue a week of runs the moment it comes back.
        next_at = advance_next_run_at(NOW - timedelta(days=7), 60, NOW)
        assert next_at > NOW
        assert next_at - NOW < timedelta(hours=2)

    def test_zero_interval_is_rejected(self) -> None:
        try:
            advance_next_run_at(None, 0, NOW)
        except ValueError:
            return
        raise AssertionError("expected a ValueError for a non-positive interval")

    def test_shard_offsets_spread_a_fleet_across_scanner_ticks(self) -> None:
        offsets = {compute_shard_offset_seconds(uuid4(), 60) for _ in range(200)}

        assert len(offsets) > 1
        assert all(offset % SCAN_INTERVAL_SECONDS == 0 for offset in offsets)
        assert max(offsets) < 60 * 60

    def test_a_multi_day_cadence_keeps_its_interval(self) -> None:
        # Flooring by minutes-into-day would snap a weekly check onto midnight and run it daily.
        weekly = 7 * 24 * 60
        next_at = advance_next_run_at(datetime(2026, 7, 28, 9, 0, tzinfo=UTC), weekly, NOW)

        assert next_at - datetime(2026, 7, 28, 9, 0, tzinfo=UTC) >= timedelta(days=6)

    def test_a_cadence_at_the_scan_interval_has_nothing_to_spread(self) -> None:
        assert compute_shard_offset_seconds(UUID(int=12345), SCAN_INTERVAL_SECONDS // 60) == 0


class TestDueCheckScan(BaseTest):
    def _check(self, **kwargs) -> DataQualityCheck:
        defaults = {
            "team": self.team,
            "subject_type": SubjectType.VIEW,
            "subject_uuid": uuid4(),
            "subject_name": "orders",
            "check_type": CheckType.NOT_NULL,
            "column_name": "customer_id",
            "fingerprint": uuid4().hex,
            "schedule_interval_minutes": 60,
            "next_run_at": datetime.now(UTC) - timedelta(minutes=1),
        }
        return DataQualityCheck.objects.for_team(self.team.id).create(**{**defaults, **kwargs})

    def test_checks_on_the_same_subject_share_one_group(self) -> None:
        subject_uuid = uuid4()
        first = self._check(subject_uuid=subject_uuid)
        second = self._check(subject_uuid=subject_uuid, column_name="total")
        self._check()

        groups = _retrieve_due_checks()

        by_subject = {group.subject_uuid: group for group in groups}
        assert sorted(by_subject[str(subject_uuid)].check_ids) == sorted([str(first.id), str(second.id)])
        assert len(groups) == 2

    @parameterized.expand(
        [
            ("disabled", {"enabled": False}),
            ("deleted", {"deleted": True}),
            ("orphaned", {"subject_status": SubjectStatus.ORPHANED}),
            ("unscheduled", {"schedule_interval_minutes": None, "next_run_at": None}),
            ("not_due_yet", {"next_run_at": datetime.now(UTC) + timedelta(hours=1)}),
        ]
    )
    def test_checks_that_should_not_run_are_not_picked_up(self, _name, overrides: dict) -> None:
        self._check(**overrides)

        assert _retrieve_due_checks() == []

    def test_a_scanned_check_is_pushed_past_now_so_a_second_scan_skips_it(self) -> None:
        check = self._check()

        assert len(_retrieve_due_checks()) == 1
        assert _retrieve_due_checks() == []

        check.refresh_from_db()
        assert check.next_run_at is not None
        assert check.next_run_at > datetime.now(UTC)


class TestRetention(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).create(team=self.team, trigger="manual")
        self.check = DataQualityCheck.objects.for_team(self.team.id).create(
            team=self.team,
            subject_type=SubjectType.VIEW,
            subject_uuid=uuid4(),
            subject_name="orders",
            check_type=CheckType.NOT_NULL,
            column_name="customer_id",
            fingerprint=uuid4().hex,
        )

    def _run(self, age_days: int) -> DataQualityCheckRun:
        run = DataQualityCheckRun.objects.for_team(self.team.id).create(
            team=self.team,
            quality_check=self.check,
            suite_run=self.suite_run,
            subject_type=SubjectType.VIEW,
            subject_uuid=self.check.subject_uuid,
            subject_name="orders",
            check_type=CheckType.NOT_NULL,
            check_fingerprint=self.check.fingerprint,
            status=CheckRunStatus.PASSED,
            observed_value=1.0,
            compiled_query="SELECT count() FROM orders",
        )
        DataQualityCheckRun.objects.unscoped().filter(pk=run.pk).update(
            created_at=datetime.now(UTC) - timedelta(days=age_days)
        )
        run.refresh_from_db()
        return run

    def test_old_compiled_queries_are_cleared_but_the_numbers_stay(self) -> None:
        old = self._run(COMPILED_QUERY_RETENTION_DAYS + 1)
        recent = self._run(1)

        _cleanup()

        old.refresh_from_db()
        recent.refresh_from_db()
        assert old.compiled_query == ""
        assert old.observed_value == 1.0
        assert recent.compiled_query != ""

    def test_the_latest_run_per_check_survives_retention(self) -> None:
        ancient_only_run = self._run(CHECK_RUN_RETENTION_DAYS + 10)

        _cleanup()

        assert DataQualityCheckRun.objects.for_team(self.team.id).filter(pk=ancient_only_run.pk).exists()

    def test_superseded_runs_past_retention_are_deleted(self) -> None:
        superseded = self._run(CHECK_RUN_RETENTION_DAYS + 10)
        newest = self._run(1)

        _cleanup()

        remaining = set(DataQualityCheckRun.objects.for_team(self.team.id).values_list("pk", flat=True))
        assert remaining == {newest.pk}
        assert superseded.pk not in remaining
