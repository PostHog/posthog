from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.query_tagging import Feature, Product, QueryTags, get_query_tags

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.facade.enums import (
    CheckRunStatus,
    CheckSeverity,
    CheckType,
    SubjectStatus,
    SubjectType,
    SuiteRunTrigger,
)
from products.data_quality.backend.logic.runner import run_check
from products.data_quality.backend.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun

RUNNER_QUERY = "products.data_quality.backend.logic.runner.execute_hogql_query"


class _Response:
    def __init__(self, columns: list[str], row: list) -> None:
        self.columns = columns
        self.results = [row]


class TestCheckRunner(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.view = DataWarehouseSavedQuery.objects.create(team=self.team, name="orders", query={"kind": "HogQLQuery"})
        self.suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger=SuiteRunTrigger.MANUAL
        )

    def _check(self, **kwargs) -> DataQualityCheck:
        defaults = {
            "team": self.team,
            "subject_type": SubjectType.VIEW,
            "saved_query_id": self.view.id,
            "subject_name": "orders",
            "check_type": CheckType.NOT_NULL,
            "column_name": "customer_id",
            "fingerprint": uuid4().hex,
        }
        return DataQualityCheck.objects.for_team(self.team.id).create(**{**defaults, **kwargs})

    @parameterized.expand(
        [
            ("no_failing_rows", 0, CheckRunStatus.PASSED),
            ("failing_rows", 7, CheckRunStatus.FAILED),
        ]
    )
    def test_zero_failing_rows_passes(self, _name, failure_count: int, expected: CheckRunStatus) -> None:
        check = self._check()
        with patch(RUNNER_QUERY, return_value=_Response(["failure_count", "observed_value"], [failure_count, 7])):
            outcome = run_check(check, self.suite_run, self.team)

        assert outcome.status == expected
        assert outcome.failed_row_count == failure_count

    @parameterized.expand(
        [
            ("within_bounds", {"min": 1, "max": 100}, 50, CheckRunStatus.PASSED),
            ("below_min", {"min": 10}, 5, CheckRunStatus.FAILED),
            ("above_max", {"max": 10}, 5000, CheckRunStatus.FAILED),
            ("on_the_boundary", {"min": 5, "max": 5}, 5, CheckRunStatus.PASSED),
        ]
    )
    def test_row_count_compares_the_observed_count_to_bounds(
        self, _name, config: dict, observed: int, expected: CheckRunStatus
    ) -> None:
        check = self._check(check_type=CheckType.ROW_COUNT, column_name="", config=config)
        with patch(RUNNER_QUERY, return_value=_Response(["observed_value"], [observed])):
            outcome = run_check(check, self.suite_run, self.team)

        assert outcome.status == expected
        assert outcome.failed_row_count is None
        assert outcome.observed_value == observed

    def test_a_broken_check_is_recorded_as_errored_rather_than_raised(self) -> None:
        check = self._check(check_type=CheckType.CUSTOM_SQL, column_name="", config={"query": "not a query at all"})

        outcome = run_check(check, self.suite_run, self.team)

        assert outcome.status == CheckRunStatus.ERRORED
        run = DataQualityCheckRun.objects.for_team(self.team.id).get(quality_check=check)
        assert run.status == CheckRunStatus.ERRORED
        assert run.error

    def test_a_gone_subject_is_skipped_and_marks_the_check_orphaned(self) -> None:
        check = self._check()
        self.view.soft_delete()

        outcome = run_check(check, self.suite_run, self.team)

        check.refresh_from_db()
        assert outcome.status == CheckRunStatus.SKIPPED
        assert check.subject_status == SubjectStatus.ORPHANED

    def test_a_hard_deleted_subject_is_skipped_without_a_history_row(self) -> None:
        check = self._check(saved_query_id=None)

        outcome = run_check(check, self.suite_run, self.team)

        check.refresh_from_db()
        assert outcome.status == CheckRunStatus.SKIPPED
        assert check.subject_status == SubjectStatus.ORPHANED
        assert not DataQualityCheckRun.objects.for_team(self.team.id).filter(quality_check=check).exists()

    def test_a_renamed_subject_heals_the_denormalized_name(self) -> None:
        check = self._check()
        self.view.name = "orders_v2"
        self.view.save()

        with patch(RUNNER_QUERY, return_value=_Response(["failure_count", "observed_value"], [0, 0])):
            run_check(check, self.suite_run, self.team)

        check.refresh_from_db()
        assert check.subject_name == "orders_v2"

    def test_observed_value_is_recorded_on_a_pass(self) -> None:
        check = self._check(check_type=CheckType.FRESHNESS, column_name="created_at", config={"max_age_minutes": 60})
        with patch(RUNNER_QUERY, return_value=_Response(["failure_count", "observed_value"], [0, 42.0])):
            run_check(check, self.suite_run, self.team)

        run = DataQualityCheckRun.objects.for_team(self.team.id).get(quality_check=check)
        assert run.status == CheckRunStatus.PASSED
        assert run.observed_value == 42.0

    def test_the_check_query_is_tagged_with_this_product_and_the_check_it_came_from(self) -> None:
        check = self._check()
        captured: list[QueryTags] = []

        def capture(*args, **kwargs) -> _Response:
            captured.append(get_query_tags())
            return _Response(["failure_count", "observed_value"], [0, 0])

        with patch(RUNNER_QUERY, side_effect=capture):
            run_check(check, self.suite_run, self.team)

        tags = captured[0]
        assert (tags.product, tags.feature) == (Product.DATA_QUALITY, Feature.DATA_QUALITY_CHECK)
        assert tags.data_quality_check_id == str(check.id)
        assert tags.data_quality_check_type == CheckType.NOT_NULL
        assert tags.data_quality_subject_type == SubjectType.VIEW
        assert tags.data_quality_subject_id == str(self.view.id)

    def test_the_stored_query_selects_failing_rows(self) -> None:
        check = self._check()
        with patch(RUNNER_QUERY, return_value=_Response(["failure_count", "observed_value"], [3, 3])):
            run_check(check, self.suite_run, self.team)

        run = DataQualityCheckRun.objects.for_team(self.team.id).get(quality_check=check)
        assert run.compiled_query == "SELECT * FROM orders WHERE isNull(customer_id)"

    @parameterized.expand(
        [
            ("first_failure", "", CheckSeverity.ERROR, True),
            ("still_failing", CheckRunStatus.FAILED, CheckSeverity.ERROR, False),
            ("warn_severity", "", CheckSeverity.WARN, False),
            ("recovered_then_failed_again", CheckRunStatus.PASSED, CheckSeverity.ERROR, True),
        ]
    )
    def test_became_failing_marks_only_error_severity_transitions(
        self, _name, previous_status: str, severity: CheckSeverity, expected: bool
    ) -> None:
        check = self._check(last_status=previous_status, severity=severity)
        with patch(RUNNER_QUERY, return_value=_Response(["failure_count", "observed_value"], [3, 3])):
            outcome = run_check(check, self.suite_run, self.team)

        assert outcome.became_failing is expected
        check.refresh_from_db()
        assert check.last_status == CheckRunStatus.FAILED
