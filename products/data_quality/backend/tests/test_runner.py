from datetime import UTC, datetime
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.query_tagging import Feature, Product, QueryTags, get_query_tags
from posthog.models.user import User

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
            # A manual run executes as its initiator so HogQL enforces that user's warehouse access:
            # a custom_sql check can't reach an object its author was denied.
            ("manual_with_user", SuiteRunTrigger.MANUAL, True, False),
            # No actor to authorize against, so the bypass stays -- otherwise every warehouse check errors.
            ("manual_without_user", SuiteRunTrigger.MANUAL, False, True),
            ("materialization_ignores_creator", SuiteRunTrigger.MATERIALIZATION, True, True),
        ]
    )
    def test_warehouse_access_control_is_enforced_only_for_user_initiated_runs(
        self, _name, trigger: SuiteRunTrigger, with_user: bool, expected_bypass: bool
    ) -> None:
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger=trigger, created_by=self.user if with_user else None
        )
        check = self._check()
        with patch(RUNNER_QUERY, return_value=_Response(["failure_count", "observed_value"], [0, 0])) as query:
            run_check(check, suite_run, self.team)

        assert query.call_args.kwargs["bypass_warehouse_access_control"] is expected_bypass
        assert query.call_args.kwargs["user"] == (None if expected_bypass else self.user)

    def _referencing_check(self, check_type: CheckType, created_by, **overrides) -> DataQualityCheck:
        # Both types read beyond their declared subject: custom_sql over arbitrary SQL, relationships
        # over a target subject. The relationships target must resolve so the check compiles.
        if check_type == CheckType.RELATIONSHIPS:
            target = DataWarehouseSavedQuery.objects.create(
                team=self.team, name="customers", query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
            )
            config = {"to_subject_type": SubjectType.VIEW, "to_subject_uuid": str(target.id), "to_column": "id"}
            return self._check(
                check_type=check_type, column_name="customer_id", config=config, created_by=created_by, **overrides
            )
        return self._check(
            check_type=check_type, column_name="", config={"query": "select 1"}, created_by=created_by, **overrides
        )

    @parameterized.expand([("custom_sql", CheckType.CUSTOM_SQL), ("relationships", CheckType.RELATIONSHIPS)])
    def test_an_automated_referencing_check_runs_as_its_author(self, _name, check_type: CheckType) -> None:
        # An automated run has no initiator, but a check that reads beyond its declared subject isn't
        # constrained to it, so it executes as the check's author to enforce that user's warehouse ACL
        # rather than bypassing it -- otherwise a check outlives its author's access to what it reads.
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger=SuiteRunTrigger.MATERIALIZATION
        )
        check = self._referencing_check(check_type, created_by=self.user)
        with patch(RUNNER_QUERY, return_value=_Response(["failure_count", "observed_value"], [0, 0])) as query:
            run_check(check, suite_run, self.team)

        assert query.call_args.kwargs["bypass_warehouse_access_control"] is False
        assert query.call_args.kwargs["user"] == self.user

    def test_an_edited_referencing_check_runs_as_whoever_last_changed_it(self) -> None:
        # The creator may never have seen what the check reads now, and may have lost access to it;
        # the editor is the one whose warehouse ACL was checked against the current definition.
        editor = User.objects.create_and_join(self.organization, "editor@posthog.com", None)
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger=SuiteRunTrigger.MATERIALIZATION
        )
        check = self._referencing_check(CheckType.CUSTOM_SQL, created_by=self.user, definition_author=editor)

        with patch(RUNNER_QUERY, return_value=_Response(["failure_count", "observed_value"], [0, 0])) as query:
            run_check(check, suite_run, self.team)

        assert query.call_args.kwargs["user"] == editor

    @parameterized.expand(
        [
            ("passing_run_stamps_it", CheckRunStatus.PASSED, [0, 0], True),
            ("failing_run_leaves_the_earlier_success", CheckRunStatus.FAILED, [3, 3], False),
        ]
    )
    def test_the_last_success_is_denormalized_onto_the_check(self, _name, expected_status, row, advances) -> None:
        # "Failing since when" can be older than any page of run history, so it cannot be derived
        # from the runs a caller fetches.
        earlier = datetime(2020, 1, 1, tzinfo=UTC)
        check = self._check(last_succeeded_at=earlier)

        with patch(RUNNER_QUERY, return_value=_Response(["failure_count", "observed_value"], row)):
            outcome = run_check(check, self.suite_run, self.team)

        assert outcome.status == expected_status
        check.refresh_from_db()
        last_succeeded_at = check.last_succeeded_at
        assert last_succeeded_at is not None
        assert (last_succeeded_at > earlier) is advances

    def test_a_failing_run_cannot_erase_a_success_recorded_beside_it(self) -> None:
        # Batches load their checks up front, so a failing run holds whatever last_succeeded_at said
        # then. Writing the column back would undo a pass another batch committed in between.
        check = self._check(last_succeeded_at=None)
        stale = DataQualityCheck.objects.for_team(self.team.id).get(id=check.id)
        succeeded_at = datetime(2026, 1, 1, tzinfo=UTC)
        DataQualityCheck.objects.for_team(self.team.id).filter(id=check.id).update(last_succeeded_at=succeeded_at)

        with patch(RUNNER_QUERY, return_value=_Response(["failure_count", "observed_value"], [3, 3])):
            run_check(stale, self.suite_run, self.team)

        stale.refresh_from_db()
        assert stale.last_succeeded_at == succeeded_at

    def test_a_run_snapshots_the_definition_it_executed(self) -> None:
        # History has to keep reading as what actually ran, even after the definition is edited.
        check = self._check(
            check_type=CheckType.ROW_COUNT, column_name="", config={"min": 1}, severity=CheckSeverity.WARN
        )
        with patch(RUNNER_QUERY, return_value=_Response(["observed_value"], [7])):
            run_check(check, self.suite_run, self.team)

        run = DataQualityCheckRun.objects.for_team(self.team.id).get(quality_check=check)
        assert run.check_config == {"min": 1}
        assert run.check_severity == CheckSeverity.WARN
        # An empty list, never null: a type that cannot reach past its own subject has to read as
        # "read nothing" rather than as history nobody can judge.
        assert run.referenced_subjects == []

    @parameterized.expand([("custom_sql", CheckType.CUSTOM_SQL), ("relationships", CheckType.RELATIONSHIPS)])
    def test_a_run_pins_the_subjects_it_read_beyond_its_own(self, _name, check_type: CheckType) -> None:
        # Recording the name would stop naming what the run read the moment the object is deleted and
        # somebody takes the name back, which is how history over a denied subject gets handed over.
        target = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="customers", query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )
        is_custom_sql = check_type == CheckType.CUSTOM_SQL
        check = self._check(
            check_type=check_type,
            column_name="" if is_custom_sql else "customer_id",
            config=(
                {"query": "SELECT 1 FROM customers"}
                if is_custom_sql
                else {"to_subject_type": SubjectType.VIEW, "to_subject_uuid": str(target.id), "to_column": "id"}
            ),
        )
        with patch(RUNNER_QUERY, return_value=_Response(["failure_count", "observed_value"], [0, 0])):
            run_check(check, self.suite_run, self.team)

        run = DataQualityCheckRun.objects.for_team(self.team.id).get(quality_check=check)
        assert run.referenced_subjects == [{"subject_type": SubjectType.VIEW, "subject_uuid": str(target.id)}]

    @parameterized.expand([("custom_sql", CheckType.CUSTOM_SQL), ("relationships", CheckType.RELATIONSHIPS)])
    def test_an_automated_referencing_check_without_an_author_errors_without_running(
        self, _name, check_type: CheckType
    ) -> None:
        # No initiator and no author means nobody to authorize the referenced subject against, so the
        # run is errored rather than executed with the warehouse ACL bypassed.
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger=SuiteRunTrigger.MATERIALIZATION
        )
        check = self._referencing_check(check_type, created_by=None)
        with patch(RUNNER_QUERY) as query:
            outcome = run_check(check, suite_run, self.team)

        query.assert_not_called()
        assert outcome.status == CheckRunStatus.ERRORED

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

    def test_an_overlapping_run_does_not_claim_the_same_failing_transition(self) -> None:
        # Stands in for a manual run racing the scheduled one: this run still holds the passing
        # status it loaded, but the row already moved to failing, so it must not notify a second time.
        check = self._check(last_status=CheckRunStatus.PASSED, severity=CheckSeverity.ERROR)
        DataQualityCheck.objects.for_team(self.team.id).filter(id=check.id).update(last_status=CheckRunStatus.FAILED)

        with patch(RUNNER_QUERY, return_value=_Response(["failure_count", "observed_value"], [3, 3])):
            outcome = run_check(check, self.suite_run, self.team)

        assert outcome.status == CheckRunStatus.FAILED
        assert outcome.became_failing is False
