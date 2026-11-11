from uuid import uuid4

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import Team

from products.data_quality.backend.facade import api
from products.data_quality.backend.facade.enums import (
    CheckRunStatus,
    CheckSeverity,
    CheckType,
    SubjectType,
    SuiteRunStatus,
    SuiteRunTrigger,
)
from products.data_quality.backend.models import DataQualityCheckRun, DataQualitySuiteRun


class TestMaterializationFailureSummary(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.job_id = uuid4()
        self.subject_id = uuid4()

    def _suite(self, **overrides: object) -> DataQualitySuiteRun:
        defaults: dict[str, object] = {
            "team": self.team,
            "trigger": SuiteRunTrigger.MATERIALIZATION,
            "status": SuiteRunStatus.COMPLETED,
            "data_modeling_job_id": self.job_id,
            "subject_type": SubjectType.VIEW,
            "subject_uuid": self.subject_id,
        }
        return DataQualitySuiteRun.objects.for_team(self.team.id).create(**(defaults | overrides))

    def _run(
        self,
        suite_run: DataQualitySuiteRun,
        *,
        check_type: CheckType | str = CheckType.NOT_NULL,
        config: dict[str, object] | None = None,
        observed_value: float | None = None,
        **overrides: object,
    ) -> DataQualityCheckRun:
        defaults: dict[str, object] = {
            "team": self.team,
            "suite_run": suite_run,
            "subject_type": SubjectType.VIEW,
            "subject_uuid": self.subject_id,
            "subject_name": "subject",
            "check_type": check_type,
            "check_fingerprint": uuid4().hex,
            "check_config": {} if config is None else config,
            "check_severity": CheckSeverity.ERROR,
            "status": CheckRunStatus.FAILED,
            "observed_value": observed_value,
        }
        return DataQualityCheckRun.objects.for_team(self.team.id).create(**(defaults | overrides))

    def _summary(self, suite_run: DataQualitySuiteRun, blocking_failures: int = 1) -> str | None:
        return api.materialization_failure_summary(
            self.team.id,
            suite_run_id=str(suite_run.id),
            data_modeling_job_id=str(self.job_id),
            saved_query_id=str(self.subject_id),
            blocking_failures=blocking_failures,
        )

    @parameterized.expand(
        [
            ("below_minimum", {"min": 1_000}, 999, "the row count is below its minimum"),
            ("above_maximum", {"max": 1_000}, 1_001, "the row count is above its maximum"),
            ("below_bounded_range", {"min": 1_000, "max": 2_000}, 999, "the row count is below its minimum"),
            ("above_bounded_range", {"min": 1_000, "max": 2_000}, 2_001, "the row count is above its maximum"),
        ]
    )
    def test_uses_safe_row_count_failure_reason(
        self, _name: str, config: dict[str, object], observed: int, expected: str
    ) -> None:
        suite_run = self._suite()
        self._run(suite_run, check_type=CheckType.ROW_COUNT, config=config, observed_value=observed)

        summary = self._summary(suite_run)
        assert summary == expected
        assert str(observed) not in summary
        assert all(str(bound) not in summary for bound in config.values())

    @parameterized.expand(
        [
            ("unique", CheckType.UNIQUE, "the uniqueness check found duplicate values"),
            ("not_null", CheckType.NOT_NULL, "the not-null check found null values"),
            (
                "accepted_values",
                CheckType.ACCEPTED_VALUES,
                "the accepted-values check found values outside its allowed set",
            ),
            ("relationships", CheckType.RELATIONSHIPS, "a data quality check failed"),
            ("freshness", CheckType.FRESHNESS, "the latest timestamp is missing or too old"),
            ("custom_sql", CheckType.CUSTOM_SQL, "a data quality check failed"),
            ("unknown", "future_type", "a data quality check failed"),
        ]
    )
    def test_uses_fixed_reasons_for_non_row_count_checks(
        self, _name: str, check_type: CheckType | str, expected: str
    ) -> None:
        suite_run = self._suite()
        self._run(suite_run, check_type=check_type, config={"value": "not displayed"}, observed_value=123)

        summary = self._summary(suite_run)
        assert summary == expected
        assert "123" not in summary
        assert "not displayed" not in summary

    def test_returns_none_when_the_blocking_count_does_not_match(self) -> None:
        suite_run = self._suite()
        self._run(suite_run)

        assert self._summary(suite_run, blocking_failures=2) is None

    def test_limits_failure_summaries(self) -> None:
        suite_run = self._suite()
        for _ in range(4):
            self._run(suite_run, check_type=CheckType.UNIQUE)

        assert self._summary(suite_run, blocking_failures=4) == (
            "the uniqueness check found duplicate values; the uniqueness check found duplicate values; "
            "the uniqueness check found duplicate values; additional checks also failed"
        )

    def test_filters_to_the_completed_materialization_suite_and_snapshot_failures(self) -> None:
        suite_run = self._suite()
        check_run = self._run(suite_run)
        assert self._summary(suite_run) == "the not-null check found null values"
        assert (
            api.materialization_failure_summary(
                self.team.id,
                suite_run_id=str(suite_run.id),
                data_modeling_job_id=str(uuid4()),
                saved_query_id=str(self.subject_id),
                blocking_failures=1,
            )
            is None
        )
        assert (
            api.materialization_failure_summary(
                self.team.id,
                suite_run_id=str(suite_run.id),
                data_modeling_job_id=str(self.job_id),
                saved_query_id=str(uuid4()),
                blocking_failures=1,
            )
            is None
        )
        other_team = Team.objects.create(organization=self.organization)
        assert (
            api.materialization_failure_summary(
                other_team.id,
                suite_run_id=str(suite_run.id),
                data_modeling_job_id=str(self.job_id),
                saved_query_id=str(self.subject_id),
                blocking_failures=1,
            )
            is None
        )

        DataQualitySuiteRun.objects.for_team(self.team.id).filter(id=suite_run.id).update(
            trigger=SuiteRunTrigger.MANUAL
        )
        assert self._summary(suite_run) is None
        DataQualitySuiteRun.objects.for_team(self.team.id).filter(id=suite_run.id).update(
            trigger=SuiteRunTrigger.MATERIALIZATION,
            status=SuiteRunStatus.RUNNING,
        )
        assert self._summary(suite_run) is None
        DataQualitySuiteRun.objects.for_team(self.team.id).filter(id=suite_run.id).update(
            status=SuiteRunStatus.COMPLETED
        )

        DataQualityCheckRun.objects.for_team(self.team.id).filter(id=check_run.id).update(
            check_severity=CheckSeverity.WARN
        )
        assert self._summary(suite_run) is None
        DataQualityCheckRun.objects.for_team(self.team.id).filter(id=check_run.id).update(
            check_severity=CheckSeverity.ERROR,
            status=CheckRunStatus.PASSED,
        )
        assert self._summary(suite_run) is None

    def test_uses_only_complete_row_count_snapshots(self) -> None:
        suite_run = self._suite()
        self._run(suite_run, check_type=CheckType.ROW_COUNT, config={"min": 1}, observed_value=None)

        assert self._summary(suite_run) == "a data quality check failed"
