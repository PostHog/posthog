from datetime import UTC, datetime, timedelta
from uuid import uuid4

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.data_quality.backend.facade.enums import (
    CheckRunStatus,
    CheckType,
    SubjectType,
    SuiteRunStatus,
    SuiteRunTrigger,
)
from products.data_quality.backend.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from products.data_quality.backend.temporal.activities.cleanup import (
    CHECK_RUN_RETENTION_DAYS,
    COMPILED_QUERY_RETENTION_DAYS,
    STALE_SUITE_HOURS,
    SUITE_RUN_RETENTION_DAYS,
    _cleanup,
)


class TestRetentionSweep(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.check = DataQualityCheck.objects.for_team(self.team.id).create(
            team=self.team,
            subject_type=SubjectType.VIEW,
            saved_query_id=uuid4(),
            subject_name="orders",
            check_type=CheckType.NOT_NULL,
            column_name="customer_id",
            fingerprint=uuid4().hex,
        )

    def _suite(self, *, age_days: float = 0, status: SuiteRunStatus = SuiteRunStatus.COMPLETED) -> DataQualitySuiteRun:
        suite = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger=SuiteRunTrigger.MANUAL, status=status
        )
        return self._age(DataQualitySuiteRun, suite, age_days)

    def _run(self, *, age_days: float = 0, **kwargs) -> DataQualityCheckRun:
        defaults = {
            "team": self.team,
            "quality_check": self.check,
            "suite_run": kwargs.pop("suite_run", None) or self._suite(),
            "subject_type": SubjectType.VIEW,
            "subject_uuid": uuid4(),
            "subject_name": "orders",
            "check_type": CheckType.NOT_NULL,
            "check_fingerprint": uuid4().hex,
            "status": CheckRunStatus.PASSED,
        }
        run = DataQualityCheckRun.objects.for_team(self.team.id).create(**{**defaults, **kwargs})
        return self._age(DataQualityCheckRun, run, age_days)

    def _age(self, model, instance, age_days: float):
        created_at = datetime.now(UTC) - timedelta(days=age_days)
        model.objects.unscoped().filter(id=instance.id).update(created_at=created_at)
        instance.refresh_from_db()
        return instance

    @parameterized.expand(
        [
            ("inside_the_window", COMPILED_QUERY_RETENTION_DAYS - 1, "SELECT 1"),
            ("past_the_window", COMPILED_QUERY_RETENTION_DAYS + 1, ""),
        ]
    )
    def test_the_compiled_query_is_cleared_only_once_it_ages_out(self, _name, age_days, expected) -> None:
        run = self._run(age_days=age_days, compiled_query="SELECT 1")

        _cleanup()

        run.refresh_from_db()
        assert run.compiled_query == expected

    def test_an_aged_run_survives_while_it_is_the_newest_for_its_check(self) -> None:
        run = self._run(age_days=CHECK_RUN_RETENTION_DAYS + 1)

        outcome = _cleanup()

        assert outcome.check_runs_deleted == 0
        assert DataQualityCheckRun.objects.unscoped().filter(id=run.id).exists()

    def test_an_aged_run_is_deleted_once_a_newer_one_exists_for_the_same_check(self) -> None:
        aged = self._run(age_days=CHECK_RUN_RETENTION_DAYS + 1)
        newest = self._run()

        _cleanup()

        surviving = set(DataQualityCheckRun.objects.unscoped().values_list("id", flat=True))
        assert surviving == {newest.id}
        assert aged.id not in surviving

    def test_an_aged_run_whose_check_is_gone_ages_out_unconditionally(self) -> None:
        orphan = self._run(age_days=CHECK_RUN_RETENTION_DAYS + 1, quality_check=None)

        _cleanup()

        assert not DataQualityCheckRun.objects.unscoped().filter(id=orphan.id).exists()

    def test_an_aged_suite_survives_while_a_check_run_still_points_at_it(self) -> None:
        suite = self._suite(age_days=SUITE_RUN_RETENTION_DAYS + 1)
        self._run(suite_run=suite)

        outcome = _cleanup()

        assert outcome.suite_runs_deleted == 0
        assert DataQualitySuiteRun.objects.unscoped().filter(id=suite.id).exists()

    def test_an_aged_suite_with_nothing_pointing_at_it_is_deleted(self) -> None:
        self._suite(age_days=SUITE_RUN_RETENTION_DAYS + 1)
        recent = self._suite(age_days=SUITE_RUN_RETENTION_DAYS - 1)

        outcome = _cleanup()

        assert outcome.suite_runs_deleted == 1
        assert set(DataQualitySuiteRun.objects.unscoped().values_list("id", flat=True)) == {recent.id}

    @parameterized.expand(
        [
            ("still_within_the_window", (STALE_SUITE_HOURS - 1) / 24, SuiteRunStatus.RUNNING),
            ("stopped_without_a_result", (STALE_SUITE_HOURS + 1) / 24, SuiteRunStatus.FAILED),
        ]
    )
    def test_a_running_suite_is_failed_once_it_is_stale(self, _name, age_days, expected_status) -> None:
        suite = self._suite(age_days=age_days, status=SuiteRunStatus.RUNNING)

        _cleanup()

        suite.refresh_from_db()
        assert suite.status == expected_status
        assert (suite.finished_at is not None) == (expected_status == SuiteRunStatus.FAILED)
