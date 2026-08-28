from datetime import UTC, datetime, timedelta
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
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
    SUBJECT_GRACE_HOURS,
    SUITE_RUN_RETENTION_DAYS,
    _cleanup,
)

BATCH_SIZE = "products.data_quality.backend.temporal.activities.cleanup.RETENTION_DELETE_BATCH_SIZE"


class TestRetentionSweep(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.view = self._view("orders")
        self.check = self._check(self.view)

    def _view(self, name: str) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=self.team, name=name, query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )

    def _check(self, view: DataWarehouseSavedQuery, *, age_days: float = 1) -> DataQualityCheck:
        check = DataQualityCheck.objects.for_team(self.team.id).create(
            team=self.team,
            subject_type=SubjectType.VIEW,
            saved_query_id=view.id,
            subject_name=view.name,
            check_type=CheckType.NOT_NULL,
            column_name="customer_id",
            fingerprint=uuid4().hex,
        )
        return self._age(DataQualityCheck, check, age_days)

    def _suite(
        self, *, age_days: float = 0, status: SuiteRunStatus = SuiteRunStatus.COMPLETED, **kwargs
    ) -> DataQualitySuiteRun:
        suite = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger=SuiteRunTrigger.MANUAL, status=status, **kwargs
        )
        return self._age(DataQualitySuiteRun, suite, age_days)

    def _run(self, *, age_days: float = 0, **kwargs) -> DataQualityCheckRun:
        defaults = {
            "team": self.team,
            "quality_check": self.check,
            "suite_run": kwargs.pop("suite_run", None) or self._suite(),
            "subject_type": SubjectType.VIEW,
            "subject_uuid": self.view.id,
            "subject_name": self.view.name,
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

    def test_expired_runs_are_deleted_one_batch_at_a_time(self) -> None:
        recent = self._run()
        [self._run(age_days=CHECK_RUN_RETENTION_DAYS + 1) for _ in range(3)]

        with patch(BATCH_SIZE, 1), CaptureQueriesContext(connection) as queries:
            outcome = _cleanup()

        assert outcome.check_runs_deleted == 3
        assert set(DataQualityCheckRun.objects.unscoped().values_list("id", flat=True)) == {recent.id}
        run_delete = f'DELETE FROM "{DataQualityCheckRun._meta.db_table}"'
        assert sum(run_delete in query["sql"] for query in queries.captured_queries) == 3

    def test_expired_suites_are_deleted_one_batch_at_a_time(self) -> None:
        for _ in range(3):
            self._suite(age_days=SUITE_RUN_RETENTION_DAYS + 1)

        with patch(BATCH_SIZE, 1), CaptureQueriesContext(connection) as queries:
            outcome = _cleanup()

        assert outcome.suite_runs_deleted == 3
        assert not DataQualitySuiteRun.objects.unscoped().exists()
        suite_delete = f'DELETE FROM "{DataQualitySuiteRun._meta.db_table}"'
        assert sum(suite_delete in query["sql"] for query in queries.captured_queries) == 3

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

    def test_a_deleted_subject_takes_its_check_runs_and_single_subject_suites(self) -> None:
        # Deleting a table or view takes its object-level denial with it, so nothing left can show a
        # restricted member was allowed the rows this history reports on. The gates withhold it
        # meanwhile; this is what ends that window.
        doomed = self._view("temp_orders")
        doomed_check = self._check(doomed)
        doomed_suite = self._suite(age_days=1, subject_type=SubjectType.VIEW, subject_uuid=doomed.id)
        doomed_run = self._run(age_days=1, quality_check=doomed_check, suite_run=doomed_suite, subject_uuid=doomed.id)
        kept_suite = self._suite(age_days=1, subject_type=SubjectType.VIEW, subject_uuid=self.view.id)
        kept_run = self._run(age_days=1, suite_run=kept_suite)
        doomed.delete()

        outcome = _cleanup()

        assert outcome.checks_deleted == 1
        assert not DataQualityCheck.objects.unscoped().filter(id=doomed_check.id).exists()
        assert not DataQualityCheckRun.objects.unscoped().filter(id=doomed_run.id).exists()
        assert not DataQualitySuiteRun.objects.unscoped().filter(id=doomed_suite.id).exists()
        assert DataQualityCheck.objects.unscoped().filter(id=self.check.id).exists()
        assert DataQualityCheckRun.objects.unscoped().filter(id=kept_run.id).exists()
        assert DataQualitySuiteRun.objects.unscoped().filter(id=kept_suite.id).exists()

    def test_rows_created_inside_the_grace_window_are_spared(self) -> None:
        # A row written while the sweep runs postdates the snapshot of live subjects it is judged
        # against, so it would read as pointing at a subject that does not exist.
        fresh = self._view("temp_orders")
        check = self._check(fresh, age_days=(SUBJECT_GRACE_HOURS - 0.5) / 24)
        run = self._run(age_days=(SUBJECT_GRACE_HOURS - 0.5) / 24, quality_check=check, subject_uuid=fresh.id)
        fresh.delete()

        _cleanup()

        assert DataQualityCheck.objects.unscoped().filter(id=check.id).exists()
        assert DataQualityCheckRun.objects.unscoped().filter(id=run.id).exists()

    def test_a_check_that_only_references_a_dead_subject_survives(self) -> None:
        # Its own subject is alive, so an admin can still see it and repoint it. Deleting it because
        # an unrelated view vanished would destroy a fixable check.
        doomed = self._view("customers")
        check = self._check(self.view)
        DataQualityCheck.objects.unscoped().filter(id=check.id).update(
            check_type=CheckType.CUSTOM_SQL, column_name="", config={"query": "SELECT 1 FROM customers"}
        )
        self._run(
            age_days=1,
            quality_check=check,
            referenced_subjects=[{"subject_type": "view", "subject_uuid": str(doomed.id)}],
        )
        doomed.delete()

        outcome = _cleanup()

        assert outcome.checks_deleted == 0
        assert DataQualityCheck.objects.unscoped().filter(id=check.id).exists()

    def test_a_sweep_suite_gives_up_the_counters_of_the_runs_it_loses(self) -> None:
        # The suite survives, because it covered a live subject too. Counters left at their original
        # totals would still report the deleted run, which is the count oracle by subtraction.
        doomed = self._view("temp_orders")
        sweep = self._suite(age_days=1)
        self._run(age_days=1, suite_run=sweep, status=CheckRunStatus.FAILED)
        self._run(age_days=1, suite_run=sweep, subject_uuid=doomed.id, status=CheckRunStatus.FAILED)
        self._run(age_days=1, suite_run=sweep, subject_uuid=doomed.id, status=CheckRunStatus.PASSED)
        DataQualitySuiteRun.objects.unscoped().filter(id=sweep.id).update(checks_failed=2, checks_passed=1)
        doomed.delete()

        _cleanup()

        sweep.refresh_from_db()
        assert (sweep.checks_failed, sweep.checks_passed) == (1, 0)

    def test_dead_subject_runs_are_deleted_one_batch_at_a_time(self) -> None:
        doomed = self._view("temp_orders")
        for _ in range(3):
            self._run(age_days=1, subject_uuid=doomed.id)
        doomed.delete()

        with patch(BATCH_SIZE, 1), CaptureQueriesContext(connection) as queries:
            outcome = _cleanup()

        assert outcome.check_runs_deleted == 3
        assert not DataQualityCheckRun.objects.unscoped().filter(subject_uuid=doomed.id).exists()
        run_delete = f'DELETE FROM "{DataQualityCheckRun._meta.db_table}"'
        assert sum(run_delete in query["sql"] for query in queries.captured_queries) == 3
