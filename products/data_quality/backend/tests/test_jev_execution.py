from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

import fakeredis
from parameterized import parameterized

from posthog.hogql import ast

from posthog.models.scoping import team_scope

from products.data_quality.backend.facade.enums import (
    CheckRunStatus,
    CheckSeverity,
    CheckType,
    SubjectType,
    SuiteRunTrigger,
)
from products.data_quality.backend.logic.contracts import SubjectRef
from products.data_quality.backend.logic.jev_execution import DurableQuestionRunner, cleanup_question_snapshots
from products.data_quality.backend.logic.jev_preview import QuestionPreviewRunner
from products.data_quality.backend.logic.jev_progress import question_progress
from products.data_quality.backend.logic.jev_question import (
    PartialQuestionDecisionsError,
    QuestionConfig,
    WeightedInput,
    question_input_query,
)
from products.data_quality.backend.models import (
    DataQualityCheck,
    DataQualityCheckRun,
    DataQualityQuestionCheckpoint,
    DataQualityQuestionExecution,
    DataQualityQuestionSnapshot,
    DataQualitySuiteRun,
)
from products.data_quality.backend.temporal.activities.question import _finish
from products.data_quality.backend.temporal.contracts import FinishQuestionInputs

EXECUTION = "products.data_quality.backend.logic.jev_execution"


@override_settings(DATA_QUALITY_JEV_MODEL_REVISION="test-deployment-v1")
class TestDurableQuestionExecution(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(team_scope(self.team.id))
        self.subject_id = uuid4()
        self.check = DataQualityCheck.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            table_id=self.subject_id,
            subject_type=SubjectType.TABLE,
            subject_name="example_orders",
            check_type=CheckType.QUESTION,
            column_name="description",
            config={"question": "Is this valid?"},
            severity=CheckSeverity.WARN,
            fingerprint=uuid4().hex,
            created_by=self.user,
        )
        self.suite = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            trigger=SuiteRunTrigger.MANUAL,
            created_by=self.user,
        )
        self.subject = SubjectRef(
            subject_type=SubjectType.TABLE,
            subject_uuid=str(self.subject_id),
            name="example_orders",
            queryable_name="example_orders",
            exists=True,
        )
        self.redis = fakeredis.FakeRedis()
        self.objects: dict[str, str] = {}
        self.inputs = [WeightedInput(text=f"example {index}", row_count=40) for index in range(500)]
        self.calls: list[str] = []

        async def source(**kwargs: object) -> AsyncIterator[WeightedInput]:
            for item in self.inputs:
                yield item

        def evaluate(inputs: list[str]) -> list[float]:
            self.calls.extend(inputs)
            return [0.9] * len(inputs)

        self.gateway = self.enterContext(patch(f"{EXECUTION}.QuestionGatewayEvaluator", return_value=evaluate))
        self.enterContext(patch(f"{EXECUTION}.warehouse_question_inputs", side_effect=source))
        self.enterContext(patch(f"{EXECUTION}.resolve_subject", return_value=self.subject))
        self.authorization = self.enterContext(patch(f"{EXECUTION}.authorize_warehouse_question_subject"))
        self.enterContext(patch(f"{EXECUTION}.validate_prompt_jev_access"))
        self.enterContext(patch(f"{EXECUTION}.get_client", return_value=self.redis))
        self.enterContext(
            patch(
                "posthog.storage.object_storage.write",
                side_effect=lambda key, content: self.objects.__setitem__(key, content),
            )
        )
        self.enterContext(
            patch("posthog.storage.object_storage.read", side_effect=lambda key, **kwargs: self.objects.get(key))
        )
        self.enterContext(
            patch("posthog.storage.object_storage.delete", side_effect=lambda key: self.objects.pop(key, None))
        )
        self.enterContext(patch("posthog.storage.object_storage.delete_objects", side_effect=self.delete_objects))

    def delete_objects(self, keys: list[str]) -> list[str]:
        for key in keys:
            self.objects.pop(key, None)
        return []

    def runner(self, suite: DataQualitySuiteRun | None = None) -> DurableQuestionRunner:
        return DurableQuestionRunner.start(self.team.id, str((suite or self.suite).id), str(self.check.id))

    def test_preview_reuses_run_decisions_without_creating_history(self) -> None:
        runner = self.runner()
        runner.prepare()
        runner.chunk(0)
        preview_module = "products.data_quality.backend.logic.jev_preview"
        with (
            patch(f"{preview_module}.authorize_warehouse_question_subject", return_value=(None, None)),
            patch(f"{preview_module}.validate_prompt_jev_access"),
            patch(f"{preview_module}.get_client", return_value=self.redis),
            patch(
                f"{preview_module}.execute_hogql_query",
                return_value=SimpleNamespace(results=[["example 0", 2], [None, 1]], error=None, hasMore=False),
            ) as query,
            patch(f"{preview_module}.QuestionGatewayEvaluator") as gateway,
        ):
            preview = QuestionPreviewRunner(
                team=self.team,
                user=self.user,
                subject=self.subject,
                config=QuestionConfig(question="Is this valid?", min_probability=0.95),
                column_name="description",
            ).run()
        assert preview.examined_row_count == 3
        assert preview.reused_decision_count == 1
        assert preview.new_decision_count == 0
        assert [item.probability for item in preview.inputs] == [0.9, None]
        assert not DataQualityCheckRun.objects.for_team(self.team.id).exists()
        gateway.assert_not_called()
        query_ast = query.call_args.kwargs["query"]
        assert query_ast.select_from.table.limit.value == 10
        full_query = question_input_query(self.subject, QuestionConfig(question="Is this valid?"), "description")
        assert isinstance(full_query.select_from, ast.JoinExpr)
        assert isinstance(full_query.select_from.table, ast.SelectQuery)
        assert full_query.select_from.table.limit is None

    def test_preview_withholds_decisions_when_source_access_is_revoked_after_inference(self) -> None:
        preview_module = "products.data_quality.backend.logic.jev_preview"
        authorization_calls = 0

        def authorize(*args: object) -> tuple[None, None]:
            nonlocal authorization_calls
            authorization_calls += 1
            if authorization_calls >= 5:
                raise ValueError("Access revoked")
            return None, None

        with (
            patch(f"{preview_module}.authorize_warehouse_question_subject", side_effect=authorize),
            patch(f"{preview_module}.validate_prompt_jev_access"),
            patch(f"{preview_module}.get_client", return_value=self.redis),
            patch(
                f"{preview_module}.execute_hogql_query",
                return_value=SimpleNamespace(results=[["new preview input", 1]], error=None, hasMore=False),
            ),
            patch(f"{preview_module}.QuestionGatewayEvaluator", return_value=lambda inputs: [0.9]),
        ):
            with self.assertRaises(ValueError):
                QuestionPreviewRunner(
                    team=self.team,
                    user=self.user,
                    subject=self.subject,
                    config=QuestionConfig(question="Is this valid?"),
                    column_name="description",
                ).run()

    def test_progress_reports_checkpointed_rows_and_hides_revoked_sources(self) -> None:
        runner = self.runner()
        runner.prepare()
        runner.chunk(0)
        with (
            patch("products.data_quality.backend.logic.jev_progress.resolve_subject", return_value=self.subject),
            patch("products.data_quality.backend.logic.jev_progress.authorize_warehouse_question_subject") as authorize,
        ):
            progress = question_progress(self.team, self.user, str(self.suite.id))
            assert len(progress) == 1
            assert progress[0].total_row_count == 20_000
            assert progress[0].evaluated_row_count == 128 * 40
            assert progress[0].completed_chunk_count == 1
            assert progress[0].total_chunk_count == 4
            authorize.side_effect = ValueError("Access revoked")
            assert question_progress(self.team, self.user, str(self.suite.id)) == []

    def test_cold_retry_and_warm_runs_preserve_frozen_coverage_and_budget(self) -> None:
        runner = self.runner()
        prepared = runner.prepare()
        runner.chunk(0)
        runner.chunk(0)
        # A retry must not rescan changed source data or reinterpret an edited definition.
        self.inputs = [WeightedInput(text="new source row", row_count=1)]
        self.check.config = {"question": "A different question?"}
        self.check.save(update_fields=["config"])
        resumed = self.runner()
        assert resumed.prepare() == prepared
        for index in range(1, prepared.chunk_count):
            resumed.chunk(index)
        result = resumed.finish()
        assert result.status == CheckRunStatus.PASSED
        assert result.examined_row_count == 20_000
        assert result.new_decision_count == 500
        assert result.coverage_complete
        assert resumed.finish() == result
        assert DataQualityCheckRun.objects.for_team(self.team.id).count() == 1
        execution = DataQualityQuestionExecution.objects.for_team(self.team.id).get(id=prepared.execution_id)
        assert execution.reserved_inference_inputs == 500
        assert DataQualityQuestionCheckpoint.objects.for_team(self.team.id).count() == 4
        self.check.config = {"question": "Is this valid?"}
        self.check.save(update_fields=["config"])
        warm_suite = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team_id=self.team.id, trigger=SuiteRunTrigger.MANUAL, created_by=self.user
        )
        self.inputs = [WeightedInput(text=f"example {index}", row_count=40) for index in range(500)]
        warm = self.runner(warm_suite)
        warm_prepared = warm.prepare()
        for index in range(warm_prepared.chunk_count):
            warm.chunk(index)
        warm_result = warm.finish()
        assert warm_result.reused_decision_count == 500
        assert warm_result.new_decision_count == 0
        assert len(self.calls) == 500

    @parameterized.expand([("incomplete", False), ("revoked", True)])
    def test_partial_or_revoked_coverage_cannot_pass(self, _name: str, revoked: bool) -> None:
        runner = self.runner()
        runner.prepare()
        runner.chunk(0)
        if revoked:
            self.authorization.side_effect = ValueError("denied")
            with self.assertRaises(ValueError):
                runner.chunk(0)
        result = runner.finish()
        assert result.status == CheckRunStatus.ERRORED
        assert not result.coverage_complete
        assert result.failure_rate is None
        assert result.completed_chunk_count == (0 if revoked else 1)
        assert DataQualityCheckRun.objects.for_team(self.team.id).get().failed_row_count is None

    @parameterized.expand(
        [
            ("empty", [], CheckRunStatus.SKIPPED),
            ("null", [WeightedInput(text=None, row_count=5)], CheckRunStatus.FAILED),
        ]
    )
    def test_deterministic_inputs_do_not_spend_credits(
        self, _name: str, inputs: list[WeightedInput], expected: CheckRunStatus
    ) -> None:
        self.inputs = inputs
        runner = self.runner()
        prepared = runner.prepare()
        for index in range(prepared.chunk_count):
            runner.chunk(index)
        result = runner.finish()
        assert result.status == expected
        assert result.coverage_complete
        self.gateway.assert_not_called()

    def test_successful_partial_decisions_survive_a_failed_chunk(self) -> None:
        self.inputs = [
            WeightedInput(text="valid batch", row_count=10),
            WeightedInput(text="failed batch", row_count=10),
        ]
        self.gateway.return_value = lambda inputs: (_ for _ in ()).throw(
            PartialQuestionDecisionsError({"valid batch": 0.9})
        )
        runner = self.runner()
        runner.prepare()
        with self.assertRaises(PartialQuestionDecisionsError):
            runner.chunk(0)
        assert not DataQualityQuestionCheckpoint.objects.for_team(self.team.id).exists()
        retried_inputs: list[str] = []

        def retry(inputs: list[str]) -> list[float]:
            retried_inputs.extend(inputs)
            return [0.9] * len(inputs)

        self.gateway.return_value = retry
        runner.chunk(0)
        result = runner.finish()
        assert retried_inputs == ["failed batch"]
        assert result.reused_decision_count == 1
        assert result.new_decision_count == 1
        assert result.examined_row_count == 20
        runner.execution.refresh_from_db()
        assert runner.execution.reserved_inference_inputs == 3

    def test_reservations_and_deadline_survive_activity_recreation(self) -> None:
        runner = self.runner()
        runner.reserve(10_000)
        resumed = self.runner()
        with self.assertRaises(ValueError):
            resumed.reserve(1)
        assert resumed.execution.deadline == runner.execution.deadline
        DataQualityQuestionExecution.objects.for_team(self.team.id).filter(id=runner.execution.id).update(
            deadline=datetime.now(UTC) - timedelta(seconds=1)
        )
        with self.assertRaises(ValueError):
            self.runner().prepare()

    def test_expired_attempts_are_cleaned_even_after_the_suite_is_deleted(self) -> None:
        runner = self.runner()
        runner.prepare()
        snapshot = DataQualityQuestionSnapshot.objects.for_team(self.team.id).get()
        snapshot.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        snapshot.save(update_fields=["expires_at"])
        self.suite.delete()
        assert cleanup_question_snapshots() == 1
        assert self.objects == {}
        assert not DataQualityQuestionSnapshot.objects.for_team(self.team.id).exists()

    def test_deleted_definition_and_expired_deadline_do_not_duplicate_a_final_result(self) -> None:
        self.inputs = [WeightedInput(text="completed input", row_count=2)]
        runner = self.runner()
        runner.prepare()
        runner.chunk(0)
        self.check.delete()
        inputs = FinishQuestionInputs(
            team_id=self.team.id,
            suite_run_id=str(self.suite.id),
            check_id=str(runner.execution.definition_id),
            errored=False,
        )
        assert _finish(inputs).passed == 1
        DataQualityQuestionExecution.objects.for_team(self.team.id).filter(id=runner.execution.id).update(
            deadline=datetime.now(UTC) - timedelta(seconds=1)
        )
        assert _finish(inputs).passed == 1
        assert DataQualityCheckRun.objects.for_team(self.team.id).count() == 1

    def test_disabled_jev_cannot_reuse_an_existing_checkpoint(self) -> None:
        runner = self.runner()
        runner.prepare()
        runner.chunk(0)
        with patch(f"{EXECUTION}.validate_prompt_jev_access", side_effect=ValueError("disabled")):
            with self.assertRaises(ValueError):
                runner.chunk(0)

    def test_failed_preparation_finalization_is_idempotent(self) -> None:
        inputs = FinishQuestionInputs(
            team_id=self.team.id, suite_run_id=str(self.suite.id), check_id=str(self.check.id), errored=True
        )
        assert _finish(inputs).errored == 1
        assert _finish(inputs).errored == 1
        assert DataQualityCheckRun.objects.for_team(self.team.id).count() == 1
