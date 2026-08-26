from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from parameterized import parameterized
from temporalio import workflow as temporal_workflow

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.facade.enums import (
    CheckRunStatus,
    CheckType,
    SubjectType,
    SuiteRunStatus,
    SuiteRunTrigger,
)
from products.data_quality.backend.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from products.data_quality.backend.temporal.activities.finalize_check_suite import _finalize
from products.data_quality.backend.temporal.activities.prepare_check_suite import _prepare
from products.data_quality.backend.temporal.activities.run_check_batch import _run_batch
from products.data_quality.backend.temporal.contracts import (
    BatchOutcome,
    CheckSuiteResult,
    FinalizeCheckSuiteInputs,
    PreparedSuite,
    RunCheckBatchInputs,
    RunCheckSuiteInputs,
)
from products.data_quality.backend.temporal.workflows.run_check_suite import RunCheckSuiteWorkflow

RUNNER_QUERY = "products.data_quality.backend.logic.runner.execute_hogql_query"
ACTIVITY_INFO = "products.data_quality.backend.temporal.activities.prepare_check_suite.activity.info"
PREPARE_FLAG = (
    "products.data_quality.backend.temporal.activities.prepare_check_suite.is_data_quality_checks_enabled_for_team_id"
)


class _Response:
    def __init__(self, columns: list[str], row: list) -> None:
        self.columns = columns
        self.results = [row]


class _ActivityInfo:
    workflow_id = "wf-1"
    workflow_run_id = "run-1"


class TestCheckSuiteActivities(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="orders", query={"kind": "HogQLQuery", "query": "SELECT 1 AS customer_id"}
        )
        flag = patch(PREPARE_FLAG, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

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

    def _prepare(self, **kwargs) -> PreparedSuite:
        inputs = RunCheckSuiteInputs(
            team_id=self.team.id,
            trigger=kwargs.pop("trigger", SuiteRunTrigger.MANUAL),
            saved_query_ids=kwargs.pop("saved_query_ids", [str(self.view.id)]),
            **kwargs,
        )
        with patch(ACTIVITY_INFO, return_value=_ActivityInfo()):
            return _prepare(inputs)

    def test_a_subject_with_no_checks_produces_no_batches(self) -> None:
        prepared = self._prepare()

        assert prepared.batches == []
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).get(id=prepared.suite_run_id)
        assert suite_run.subject_uuid == self.view.id

    def test_a_suite_spanning_several_subjects_records_none_of_them(self) -> None:
        other_view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="refunds", query={"kind": "HogQLQuery"}
        )

        prepared = self._prepare(saved_query_ids=[str(self.view.id), str(other_view.id)])

        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).get(id=prepared.suite_run_id)
        assert suite_run.subject_uuid is None
        assert suite_run.subject_type == ""

    def test_disabled_and_deleted_checks_are_not_selected(self) -> None:
        runnable = self._check()
        self._check(enabled=False)
        self._check(deleted=True)

        prepared = self._prepare()

        assert prepared.batches == [[str(runnable.id)]]

    def test_table_checks_are_selected_by_table_ids(self) -> None:
        table_id = uuid4()
        on_table = self._check(saved_query_id=None, table_id=table_id, subject_type=SubjectType.TABLE)
        self._check()

        prepared = self._prepare(saved_query_ids=[], table_ids=[str(table_id)], trigger=SuiteRunTrigger.SOURCE_SYNC)

        assert prepared.batches == [[str(on_table.id)]]
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).get(id=prepared.suite_run_id)
        assert suite_run.subject_type == SubjectType.TABLE
        assert suite_run.subject_uuid == table_id

    def test_an_unflagged_org_prepares_an_empty_suite(self) -> None:
        self._check()

        with patch(PREPARE_FLAG, return_value=False):
            prepared = self._prepare()

        assert prepared.batches == []

    def test_a_batch_counts_each_outcome_and_records_a_run_per_check(self) -> None:
        passing = self._check()
        failing = self._check(column_name="total")
        erroring = self._check(check_type=CheckType.CUSTOM_SQL, column_name="", config={"query": "nonsense ((("})
        prepared = self._prepare()

        def _fake_query(query, team, query_type, **kwargs):
            failure_count = 4 if "total" in str(query.to_hogql()) else 0
            return _Response(["failure_count", "observed_value"], [failure_count, failure_count])

        with patch(RUNNER_QUERY, side_effect=_fake_query):
            outcome = _run_batch(
                RunCheckBatchInputs(
                    team_id=self.team.id,
                    suite_run_id=prepared.suite_run_id,
                    check_ids=[str(passing.id), str(failing.id), str(erroring.id)],
                )
            )

        assert (outcome.passed, outcome.failed, outcome.errored) == (1, 1, 1)
        assert outcome.failed_blocking == 1
        assert outcome.newly_failing_check_ids == [str(failing.id)]
        runs = DataQualityCheckRun.objects.for_team(self.team.id).filter(suite_run_id=prepared.suite_run_id)
        assert runs.count() == 3
        assert runs.get(quality_check=erroring).status == CheckRunStatus.ERRORED

    def test_a_check_disabled_after_prepare_is_not_run(self) -> None:
        stays = self._check()
        disabled_later = self._check(column_name="total")
        prepared = self._prepare()

        DataQualityCheck.objects.for_team(self.team.id).filter(id=disabled_later.id).update(enabled=False)

        with patch(RUNNER_QUERY, return_value=_Response(["failure_count", "observed_value"], [0, 0])):
            outcome = _run_batch(
                RunCheckBatchInputs(
                    team_id=self.team.id,
                    suite_run_id=prepared.suite_run_id,
                    check_ids=[str(stays.id), str(disabled_later.id)],
                )
            )

        assert outcome.passed == 1
        runs = DataQualityCheckRun.objects.for_team(self.team.id).filter(suite_run_id=prepared.suite_run_id)
        assert list(runs.values_list("quality_check_id", flat=True)) == [stays.id]

    def test_a_staged_audit_that_cannot_reach_the_staged_files_runs_no_check(self) -> None:
        check = self._check()
        prepared = self._prepare()

        with patch(RUNNER_QUERY) as query:
            outcome = _run_batch(
                RunCheckBatchInputs(
                    team_id=self.team.id,
                    suite_run_id=prepared.suite_run_id,
                    check_ids=[str(check.id)],
                    staged_queryable_folder="query_2000000000000",
                    staged_saved_query_id=str(self.view.id),
                )
            )

        query.assert_not_called()
        assert (outcome.errored, outcome.failed_blocking) == (1, 0)
        run = DataQualityCheckRun.objects.for_team(self.team.id).get(suite_run_id=prepared.suite_run_id)
        assert run.status == CheckRunStatus.ERRORED
        assert "staged files" in run.error

    def test_finalize_sums_batch_outcomes_into_the_report(self) -> None:
        prepared = self._prepare()

        result = _finalize(
            FinalizeCheckSuiteInputs(
                team_id=self.team.id,
                suite_run_id=prepared.suite_run_id,
                outcomes=[BatchOutcome(passed=2, failed=1, failed_blocking=1), BatchOutcome(passed=3, errored=1)],
            )
        )

        assert (result.checks_passed, result.checks_failed, result.checks_errored) == (5, 1, 1)
        assert result.checks_failed_blocking == 1
        assert result.status == SuiteRunStatus.COMPLETED


class TestRunCheckSuiteWorkflow(BaseTest):
    def _run(self, prepared: PreparedSuite, activity_results: list) -> tuple[CheckSuiteResult, AsyncMock]:
        execute_activity = AsyncMock(side_effect=[prepared, *activity_results])
        with patch.object(temporal_workflow, "execute_activity", new=execute_activity):
            result = async_to_sync(RunCheckSuiteWorkflow().run)(
                RunCheckSuiteInputs(team_id=self.team.id, trigger=SuiteRunTrigger.MANUAL)
            )
        return result, execute_activity

    def test_an_empty_suite_skips_the_batch_activities(self) -> None:
        empty = CheckSuiteResult(suite_run_id="s-1", status=SuiteRunStatus.EMPTY)

        result, execute_activity = self._run(PreparedSuite(suite_run_id="s-1", batches=[]), [empty])

        assert result.status == SuiteRunStatus.EMPTY
        started = [call.args[0].__name__ for call in execute_activity.await_args_list]
        assert started == ["prepare_check_suite_activity", "mark_check_suite_empty_activity"]

    def test_every_batch_is_run_and_folded_into_finalize(self) -> None:
        prepared = PreparedSuite(suite_run_id="s-1", batches=[["a"], ["b"]])
        completed = CheckSuiteResult(suite_run_id="s-1", status=SuiteRunStatus.COMPLETED)

        result, execute_activity = self._run(prepared, [BatchOutcome(passed=1), BatchOutcome(failed=1), completed])

        assert result.status == SuiteRunStatus.COMPLETED
        started = [call.args[0].__name__ for call in execute_activity.await_args_list]
        assert started == [
            "prepare_check_suite_activity",
            "run_check_batch_activity",
            "run_check_batch_activity",
            "finalize_check_suite_activity",
        ]
        finalize_inputs = execute_activity.await_args_list[-1].args[1]
        assert [outcome.passed for outcome in finalize_inputs.outcomes] == [1, 0]

    def test_a_failed_batch_marks_the_prepared_suite_failed_and_reraises(self) -> None:
        prepared = PreparedSuite(suite_run_id="s-1", batches=[["a"]])
        boom = RuntimeError("batch exhausted its retries")
        execute_activity = AsyncMock(side_effect=[prepared, boom, None])

        with patch.object(temporal_workflow, "execute_activity", new=execute_activity):
            with self.assertRaises(RuntimeError):
                async_to_sync(RunCheckSuiteWorkflow().run)(
                    RunCheckSuiteInputs(team_id=self.team.id, trigger=SuiteRunTrigger.MANUAL)
                )

        started = [call.args[0].__name__ for call in execute_activity.await_args_list]
        assert started == [
            "prepare_check_suite_activity",
            "run_check_batch_activity",
            "mark_check_suite_failed_activity",
        ]
        assert execute_activity.await_args_list[-1].args[1].suite_run_id == "s-1"

    @parameterized.expand(
        [
            ("with_a_precreated_row", "pre-1", ["prepare_check_suite_activity", "mark_check_suite_failed_activity"]),
            ("without_a_row", None, ["prepare_check_suite_activity"]),
        ]
    )
    def test_a_prepare_failure_marks_only_a_precreated_row(self, _name, suite_run_id, expected_activities) -> None:
        execute_activity = AsyncMock(side_effect=[RuntimeError("prepare exhausted its retries"), None])

        with patch.object(temporal_workflow, "execute_activity", new=execute_activity):
            with self.assertRaises(RuntimeError):
                async_to_sync(RunCheckSuiteWorkflow().run)(
                    RunCheckSuiteInputs(team_id=self.team.id, trigger=SuiteRunTrigger.MANUAL, suite_run_id=suite_run_id)
                )

        started = [call.args[0].__name__ for call in execute_activity.await_args_list]
        assert started == expected_activities
        if suite_run_id is not None:
            assert execute_activity.await_args_list[-1].args[1].suite_run_id == suite_run_id
