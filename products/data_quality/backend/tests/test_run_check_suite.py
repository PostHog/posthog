from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync
from parameterized import parameterized
from temporalio import workflow as temporal_workflow
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

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
    DueCheckGroup,
    FinalizeCheckSuiteInputs,
    PreparedSuite,
    RunCheckBatchInputs,
    RunCheckSuiteInputs,
)
from products.data_quality.backend.temporal.workflows.run_check_suite import RunCheckSuiteWorkflow
from products.data_quality.backend.temporal.workflows.schedule_due_checks import ScheduleDueChecksWorkflow

RUNNER_QUERY = "products.data_quality.backend.logic.runner.execute_hogql_query"
ACTIVITY_INFO = "products.data_quality.backend.temporal.activities.prepare_check_suite.activity.info"


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
        self.view = DataWarehouseSavedQuery.objects.create(team=self.team, name="orders", query={"kind": "HogQLQuery"})

    def _check(self, **kwargs) -> DataQualityCheck:
        defaults = {
            "team": self.team,
            "subject_type": SubjectType.VIEW,
            "subject_uuid": self.view.id,
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
            subject_type=SubjectType.VIEW,
            subject_uuids=[str(self.view.id)],
            **kwargs,
        )
        with patch(ACTIVITY_INFO, return_value=_ActivityInfo()):
            return _prepare(inputs)

    def test_a_subject_with_no_checks_produces_no_batches(self) -> None:
        prepared = self._prepare()

        assert prepared.batches == []
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).get(id=prepared.suite_run_id)
        assert suite_run.subject_uuid == self.view.id

    def test_disabled_and_deleted_checks_are_not_selected(self) -> None:
        runnable = self._check()
        self._check(enabled=False)
        self._check(deleted=True)

        prepared = self._prepare()

        assert prepared.batches == [[str(runnable.id)]]

    def test_materialization_only_runs_checks_that_opted_in(self) -> None:
        opted_in = self._check()
        self._check(run_on_materialization=False)

        prepared = self._prepare(trigger=SuiteRunTrigger.MATERIALIZATION)

        assert prepared.batches == [[str(opted_in.id)]]

    def test_a_batch_counts_each_outcome_and_records_a_run_per_check(self) -> None:
        passing = self._check()
        failing = self._check(column_name="total")
        erroring = self._check(check_type=CheckType.CUSTOM_SQL, column_name="", config={"query": "nonsense ((("})
        prepared = self._prepare()

        def _fake_query(query, team, query_type):
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
        assert outcome.newly_failing_check_ids == [str(failing.id)]
        runs = DataQualityCheckRun.objects.for_team(self.team.id).filter(suite_run_id=prepared.suite_run_id)
        assert runs.count() == 3
        assert runs.get(quality_check=erroring).status == CheckRunStatus.ERRORED

    def test_a_check_disabled_after_prepare_is_not_run(self) -> None:
        # Prepare picks up both, then the user disables one before the batch executes. The batch
        # reloads and must honor "disabled checks are never run" rather than trusting prepare's ids.
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

    def test_finalize_sums_batch_outcomes_into_the_report(self) -> None:
        prepared = self._prepare()

        result = _finalize(
            FinalizeCheckSuiteInputs(
                team_id=self.team.id,
                suite_run_id=prepared.suite_run_id,
                outcomes=[BatchOutcome(passed=2, failed=1), BatchOutcome(passed=3, errored=1)],
            )
        )

        assert (result.checks_passed, result.checks_failed, result.checks_errored) == (5, 1, 1)
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
        # Without the failure path an exhausted retry leaves the suite RUNNING forever, so a poller
        # never sees a terminal state. The workflow must mark it failed, then still re-raise.
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
        # A prepare that never committed a row has nothing to finalize; one handed a pre-created row
        # (the API path) must mark that row failed so its poller is not stranded.
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


class TestScheduleDueChecksWorkflow(BaseTest):
    def _groups(self, count: int) -> list[DueCheckGroup]:
        return [
            DueCheckGroup(
                team_id=self.team.id,
                subject_type=SubjectType.VIEW,
                subject_uuid=str(uuid4()),
                check_ids=["c"],
            )
            for _ in range(count)
        ]

    def _run(self, groups: list[DueCheckGroup], start_child: AsyncMock) -> int:
        retrieve = AsyncMock(return_value=groups)
        # workflow.logger reaches into the workflow runtime, which is absent when the coroutine is
        # driven directly by async_to_sync rather than a Worker, so stub it at that boundary.
        with (
            patch.object(temporal_workflow, "execute_activity", new=retrieve),
            patch.object(temporal_workflow, "start_child_workflow", new=start_child),
            patch.object(temporal_workflow, "logger", new=MagicMock()),
        ):
            return async_to_sync(ScheduleDueChecksWorkflow().run)()

    def test_a_child_start_failure_is_surfaced_not_swallowed(self) -> None:
        # return_exceptions=True used to fold a failed start into a count and let the scan succeed,
        # silently losing that group for a cadence. The scan must fail loudly instead, and it must
        # still attempt every group rather than stopping at the first failure.
        groups = self._groups(3)
        start_child = AsyncMock(side_effect=[None, RuntimeError("could not start"), None])

        with self.assertRaises(ApplicationError):
            self._run(groups, start_child)

        assert start_child.await_count == 3

    def test_an_already_running_subject_is_skipped_without_failing_the_scan(self) -> None:
        # An overlapping scan hitting a subject whose suite is still open is expected, not an error.
        groups = self._groups(2)
        start_child = AsyncMock(side_effect=[WorkflowAlreadyStartedError("id", "data-quality-run-suite"), None])

        assert self._run(groups, start_child) == 2
