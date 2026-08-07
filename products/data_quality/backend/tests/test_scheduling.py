from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.data_quality.backend.facade.enums import (
    CheckRunStatus,
    CheckType,
    SubjectStatus,
    SubjectType,
    SuiteRunStatus,
)
from products.data_quality.backend.logic.scheduling import (
    SCAN_INTERVAL_SECONDS,
    advance_next_run_at,
    compute_shard_offset_seconds,
)
from products.data_quality.backend.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from products.data_quality.backend.temporal.activities.cleanup import (
    CHECK_RUN_RETENTION_DAYS,
    COMPILED_QUERY_RETENTION_DAYS,
    SUITE_RUN_RETENTION_DAYS,
    _cleanup,
)
from products.data_quality.backend.temporal.activities.schedule_due_checks import _retrieve_due_checks

NOW = datetime(2026, 7, 28, 12, 7, 30, tzinfo=UTC)


EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class TestSchedulingMath:
    def test_hourly_lands_on_the_next_top_of_the_hour(self) -> None:
        assert advance_next_run_at(60, NOW) == datetime(2026, 7, 28, 13, 0, tzinfo=UTC)

    def test_a_slot_exactly_at_now_advances_to_the_following_one(self) -> None:
        # The scanner claims a check when next_run_at <= now, so a slot landing exactly on now must
        # move forward, never return now itself and get re-claimed on the same tick.
        on_the_hour = datetime(2026, 7, 28, 13, 0, tzinfo=UTC)
        assert advance_next_run_at(60, on_the_hour) == datetime(2026, 7, 28, 14, 0, tzinfo=UTC)

    def test_zero_interval_is_rejected(self) -> None:
        try:
            advance_next_run_at(0, NOW)
        except ValueError:
            return
        raise AssertionError("expected a ValueError for a non-positive interval")

    @parameterized.expand(
        [
            ("daily_offset_by_twelve_hours", 24 * 60, 12 * 3600),
            ("weekly_offset_by_three_days", 7 * 24 * 60, 3 * 24 * 3600),
        ]
    )
    def test_a_non_zero_offset_is_applied_once_and_the_cadence_holds(self, _name, interval, offset) -> None:
        # The regression this guards: re-adding the offset to an already-phased slot made a daily
        # 12h-offset check advance by 36h, and weekly cadences drift the same way. Feeding one
        # result back in must yield exactly one interval later.
        first = advance_next_run_at(interval, NOW, shard_offset_seconds=offset)
        second = advance_next_run_at(interval, first, shard_offset_seconds=offset)

        assert second - first == timedelta(minutes=interval)
        # The offset phases the grid exactly once: every slot sits offset seconds past a whole
        # number of intervals from the fixed epoch anchor.
        assert int((first - EPOCH).total_seconds()) % (interval * 60) == offset

    def test_shard_offsets_spread_a_fleet_across_scanner_ticks(self) -> None:
        offsets = {compute_shard_offset_seconds(uuid4(), 60) for _ in range(200)}

        assert len(offsets) > 1
        assert all(offset % SCAN_INTERVAL_SECONDS == 0 for offset in offsets)
        assert max(offsets) < 60 * 60

    def test_a_multi_day_cadence_keeps_its_interval(self) -> None:
        # Anchoring on a within-day grid would snap a weekly check onto midnight and run it daily.
        weekly = 7 * 24 * 60
        first = advance_next_run_at(weekly, NOW)
        second = advance_next_run_at(weekly, first)

        assert second - first == timedelta(days=7)

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

    def _run(self, age_days: int, suite_run: DataQualitySuiteRun | None = None) -> DataQualityCheckRun:
        run = DataQualityCheckRun.objects.for_team(self.team.id).create(
            team=self.team,
            quality_check=self.check,
            suite_run=suite_run or self.suite_run,
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

    def _aged_suite(self, age_days: int, status: str = SuiteRunStatus.COMPLETED) -> DataQualitySuiteRun:
        suite = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger="schedule", status=status
        )
        DataQualitySuiteRun.objects.unscoped().filter(pk=suite.pk).update(
            created_at=datetime.now(UTC) - timedelta(days=age_days)
        )
        suite.refresh_from_db()
        return suite

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

    def test_an_aged_completed_suite_with_no_runs_is_deleted(self) -> None:
        # Before the fix only EMPTY suites aged out, so completed scheduled runs piled up forever
        # even after their check runs were swept away.
        orphaned = self._aged_suite(SUITE_RUN_RETENTION_DAYS + 5)

        _cleanup()

        assert not DataQualitySuiteRun.objects.for_team(self.team.id).filter(pk=orphaned.pk).exists()

    def test_an_aged_suite_survives_while_a_check_run_still_points_at_it(self) -> None:
        backed = self._aged_suite(SUITE_RUN_RETENTION_DAYS + 5)
        self._run(1, suite_run=backed)

        _cleanup()

        assert DataQualitySuiteRun.objects.for_team(self.team.id).filter(pk=backed.pk).exists()
