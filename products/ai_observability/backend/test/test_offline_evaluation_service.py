from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Event
from typing import Literal
from uuid import uuid4

from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team

from products.ai_observability.backend.models.datasets import Dataset, DatasetItem, DatasetItemVersion, DatasetRevision
from products.ai_observability.backend.models.offline_evaluations import (
    OfflineEvaluationResult,
    OfflineEvaluationResultPayload,
    OfflineExperiment,
    OfflineExperimentItem,
    OfflineExperimentItemPayload,
    PayloadState,
)
from products.ai_observability.backend.models.score_definitions import ScoreDefinition, ScoreDefinitionVersion
from products.ai_observability.backend.offline_evaluation_service import (
    ExperimentReceipt,
    OfflineEvaluationConflict,
    OfflineEvaluationIngestionService,
    OfflineEvaluationNotFound,
    OfflineEvaluationValidationError,
    OfflineExperimentService,
    UploadReceipt,
)
from products.ai_observability.backend.offline_evaluation_types import (
    ExperimentSubmission,
    ItemSubmission,
    ResultSubmission,
    UploadSubmission,
)


class TestOfflineEvaluationService(TestCase):
    team: Team
    other_team: Team
    scorer: ScoreDefinition
    version: ScoreDefinitionVersion
    other_version: ScoreDefinitionVersion

    @classmethod
    def setUpTestData(cls) -> None:
        organization, _, cls.team = Organization.objects.bootstrap(None)
        cls.other_team = Team.objects.create(organization=organization)
        cls.scorer = ScoreDefinition.objects.create(team=cls.team, name="Accuracy", kind="numeric")
        cls.version = cls.scorer.create_new_version(config={"min": 0, "max": 1}, created_by=None)
        other_scorer = ScoreDefinition.objects.create(team=cls.other_team, name="Other scorer", kind="numeric")
        cls.other_version = other_scorer.create_new_version(config={}, created_by=None)

    def setUp(self) -> None:
        self.lifecycle = OfflineExperimentService(team_id=self.team.id)
        self.ingestion = OfflineEvaluationIngestionService(team_id=self.team.id)
        self.experiment_submission = ExperimentSubmission(
            id=uuid4(), name="Candidate model", started_at=timezone.now(), run_source="ci"
        )
        self.experiment = self.lifecycle.create(self.experiment_submission).experiment
        self.item = ItemSubmission(id=uuid4(), payload={"input": "A question", "output": "An answer"})
        self.result = ResultSubmission(
            item_id=self.item.id,
            scorer_version_id=self.version.id,
            status="ok",
            value=0.8,
            payload={"reasoning": "The answer addresses the question."},
        )
        self.submission = UploadSubmission(items=[self.item], results=[self.result])

    def test_experiment_creation_is_idempotent_and_rejects_changed_content(self) -> None:
        retry = self.lifecycle.create(self.experiment_submission)
        self.assertFalse(retry.created)
        self.assertEqual(retry.experiment.created_at, self.experiment.created_at)
        self.assertEqual(retry.counts.accepted_item_count, 0)

        with self.assertRaises(OfflineEvaluationConflict) as error:
            self.lifecycle.create(replace(self.experiment_submission, name="Different model"))
        self.assertEqual(error.exception.code, "content_conflict")
        self.assertEqual(OfflineExperiment.objects.for_team(self.team.id).count(), 1)

    def test_upload_retry_preserves_identity_acceptance_and_retention(self) -> None:
        accepted = self.ingestion.upload(self.experiment.id, self.submission)
        replay = self.ingestion.upload(self.experiment.id, self.submission)

        self.assertEqual(replay.items, [replace(accepted.items[0], created=False)])
        self.assertEqual(replay.results, [replace(accepted.results[0], created=False)])
        self.assertTrue(accepted.items[0].created)
        self.assertTrue(accepted.results[0].created)
        item = OfflineExperimentItem.objects.for_team(self.team.id).get(id=self.item.id)
        result = OfflineEvaluationResult.objects.for_team(self.team.id).get(id=accepted.results[0].id)
        self.assertEqual(item.payload_expires_at, item.accepted_at + timedelta(days=30))
        self.assertEqual(result.payload_expires_at, result.accepted_at + timedelta(days=30))
        self.assertEqual(
            OfflineExperimentItemPayload.objects.for_team(self.team.id).get(item=item).data, self.item.payload
        )
        self.assertEqual(
            OfflineEvaluationResultPayload.objects.for_team(self.team.id).get(result=result).data, self.result.payload
        )

    @parameterized.expand([("item",), ("result",)])
    def test_changed_accepted_content_conflicts(self, target: str) -> None:
        self.ingestion.upload(self.experiment.id, self.submission)
        changed = (
            replace(self.submission, items=[replace(self.item, payload={"input": "A different question"})])
            if target == "item"
            else replace(self.submission, results=[replace(self.result, value=0.9)])
        )

        with self.assertRaises(OfflineEvaluationConflict) as error:
            self.ingestion.upload(self.experiment.id, changed)
        self.assertEqual(error.exception.code, "content_conflict")
        self.assertEqual(OfflineEvaluationResult.objects.for_team(self.team.id).get().numeric_value, 0.8)

    @parameterized.expand([("missing_scorer",), ("foreign_scorer",), ("invalid_score",)])
    def test_invalid_batch_does_not_persist_any_rows(self, failure: str) -> None:
        second_item = replace(self.item, id=uuid4())
        second_result = replace(self.result, item_id=second_item.id)
        if failure == "missing_scorer":
            second_result = replace(second_result, scorer_version_id=uuid4())
        elif failure == "foreign_scorer":
            second_result = replace(second_result, scorer_version_id=self.other_version.id)
        else:
            second_result = replace(second_result, value=2.0)

        with self.assertRaises(OfflineEvaluationValidationError) as error:
            self.ingestion.upload(
                self.experiment.id,
                UploadSubmission(items=[self.item, second_item], results=[self.result, second_result]),
            )
        self.assertTrue(error.exception.field.startswith("results.1."))
        self.assertFalse(OfflineExperimentItem.objects.for_team(self.team.id).exists())
        self.assertFalse(OfflineEvaluationResult.objects.for_team(self.team.id).exists())
        self.assertFalse(OfflineExperimentItemPayload.objects.for_team(self.team.id).exists())
        self.assertFalse(OfflineEvaluationResultPayload.objects.for_team(self.team.id).exists())

    def test_additional_scorer_uses_existing_item_without_payload(self) -> None:
        self.ingestion.upload(self.experiment.id, self.submission)
        scorer = ScoreDefinition.objects.create(team=self.team, name="Safety", kind="boolean")
        version = scorer.create_new_version(config={}, created_by=None)

        receipt = self.ingestion.upload(
            self.experiment.id,
            UploadSubmission(
                results=[ResultSubmission(item_id=self.item.id, scorer_version_id=version.id, status="ok", value=False)]
            ),
        )

        self.assertFalse(receipt.items[0].created)
        self.assertTrue(receipt.results[0].created)
        self.assertEqual(OfflineExperimentItem.objects.for_team(self.team.id).count(), 1)
        self.assertEqual(OfflineExperimentItemPayload.objects.for_team(self.team.id).count(), 1)
        self.assertEqual(OfflineEvaluationResult.objects.for_team(self.team.id).count(), 2)
        self.assertIs(
            OfflineEvaluationResult.objects.for_team(self.team.id).get(id=receipt.results[0].id).boolean_value, False
        )

    @parameterized.expand([("unknown",), ("foreign",)])
    def test_inaccessible_experiment_is_not_found_for_upload_and_close(self, target: str) -> None:
        experiment_id = uuid4() if target == "unknown" else self.experiment.id
        team_id = self.team.id if target == "unknown" else self.other_team.id
        with self.assertRaises(OfflineEvaluationNotFound):
            OfflineEvaluationIngestionService(team_id=team_id).upload(experiment_id, self.submission)
        with self.assertRaises(OfflineEvaluationNotFound):
            OfflineExperimentService(team_id=team_id).close(experiment_id, status="failed")

    @parameterized.expand([("unknown",), ("other_experiment",), ("other_project",)])
    def test_result_cannot_reference_an_item_outside_its_experiment(self, target: str) -> None:
        if target != "unknown":
            self.ingestion.upload(self.experiment.id, self.submission)
        team_id = self.other_team.id if target == "other_project" else self.team.id
        experiment = (
            OfflineExperimentService(team_id=team_id).create(replace(self.experiment_submission, id=uuid4())).experiment
        )
        result = (
            replace(self.result, scorer_version_id=self.other_version.id) if target == "other_project" else self.result
        )

        with self.assertRaises(OfflineEvaluationValidationError) as error:
            OfflineEvaluationIngestionService(team_id=team_id).upload(experiment.id, UploadSubmission(results=[result]))
        self.assertEqual(error.exception.field, "results.0.item_id")

    @parameterized.expand([("experiment",), ("item",)])
    def test_global_uuid_collision_returns_a_controlled_conflict(self, target: str) -> None:
        other_lifecycle = OfflineExperimentService(team_id=self.other_team.id)
        if target == "experiment":
            with self.assertRaises(OfflineEvaluationConflict) as error:
                other_lifecycle.create(self.experiment_submission)
        else:
            self.ingestion.upload(self.experiment.id, self.submission)
            other_experiment = other_lifecycle.create(replace(self.experiment_submission, id=uuid4())).experiment
            with self.assertRaises(OfflineEvaluationConflict) as error:
                OfflineEvaluationIngestionService(team_id=self.other_team.id).upload(
                    other_experiment.id,
                    replace(self.submission, results=[replace(self.result, scorer_version_id=self.other_version.id)]),
                )
            self.assertFalse(OfflineEvaluationResult.objects.for_team(self.other_team.id).exists())
        self.assertEqual(error.exception.code, "identity_conflict")

    def test_completion_checks_counts_and_counts_error_results(self) -> None:
        experiment = self.lifecycle.create(
            replace(self.experiment_submission, id=uuid4(), expected_item_count=1, expected_result_count=2)
        ).experiment
        self.ingestion.upload(experiment.id, self.submission)

        with self.assertRaises(OfflineEvaluationConflict) as error:
            self.lifecycle.close(experiment.id, status="completed")
        self.assertEqual(error.exception.code, "expected_count_mismatch")
        self.assertIsNotNone(error.exception.counts)
        assert error.exception.counts is not None
        self.assertEqual(error.exception.counts.accepted_result_count, 1)
        self.assertEqual(error.exception.counts.expected_result_count, 2)
        experiment.refresh_from_db()
        self.assertEqual(experiment.status, "uploading")
        self.assertIsNone(experiment.finished_at)

        second_version = self.scorer.create_new_version(config={}, created_by=None)
        self.ingestion.upload(
            experiment.id,
            UploadSubmission(
                results=[
                    replace(
                        self.result,
                        scorer_version_id=second_version.id,
                        status="error",
                        value=None,
                        error_code="timeout",
                    )
                ]
            ),
        )
        closed = self.lifecycle.close(experiment.id, status="completed")
        self.assertEqual(closed.experiment.status, "completed")
        self.assertEqual(closed.counts.accepted_result_count, 2)

    @parameterized.expand([("completed",), ("failed",)])
    def test_closure_allows_exact_replays_and_rejects_new_data(self, status: Literal["completed", "failed"]) -> None:
        accepted = self.ingestion.upload(self.experiment.id, self.submission)
        closed = self.lifecycle.close(self.experiment.id, status=status)
        repeated = self.lifecycle.close(self.experiment.id, status=status)
        self.assertEqual(repeated.experiment.finished_at, closed.experiment.finished_at)
        replay = self.ingestion.upload(self.experiment.id, self.submission)
        self.assertEqual(replay.results[0], replace(accepted.results[0], created=False))
        self.assertEqual(self.lifecycle.create(self.experiment_submission).experiment.status, status)

        second_item = replace(self.item, id=uuid4())
        with self.assertRaises(OfflineEvaluationConflict) as error:
            self.ingestion.upload(
                self.experiment.id,
                UploadSubmission(
                    items=[second_item], results=[self.result, replace(self.result, item_id=second_item.id)]
                ),
            )
        self.assertEqual(error.exception.code, "experiment_closed")
        self.assertEqual(OfflineExperimentItem.objects.for_team(self.team.id).count(), 1)
        with self.assertRaises(OfflineEvaluationConflict):
            self.lifecycle.close(self.experiment.id, status="failed" if status == "completed" else "completed")

    def test_failed_closure_preserves_results_despite_missing_expected_counts(self) -> None:
        experiment = self.lifecycle.create(
            replace(self.experiment_submission, id=uuid4(), expected_item_count=10, expected_result_count=30)
        ).experiment
        self.ingestion.upload(experiment.id, self.submission)

        receipt = self.lifecycle.close(experiment.id, status="failed")
        self.assertEqual(receipt.experiment.status, "failed")
        self.assertEqual(receipt.counts.accepted_result_count, 1)

    def test_retry_after_payload_expiry_does_not_restore_payloads_or_extend_retention(self) -> None:
        accepted = self.ingestion.upload(self.experiment.id, self.submission)
        item = OfflineExperimentItem.objects.for_team(self.team.id).get(id=self.item.id)
        result = OfflineEvaluationResult.objects.for_team(self.team.id).get(id=accepted.results[0].id)
        OfflineExperimentItemPayload.objects.for_team(self.team.id).filter(item=item).delete()
        OfflineEvaluationResultPayload.objects.for_team(self.team.id).filter(result=result).delete()
        OfflineExperimentItem.objects.for_team(self.team.id).filter(id=item.id).update(
            payload_state=PayloadState.EXPIRED
        )
        OfflineEvaluationResult.objects.for_team(self.team.id).filter(id=result.id).update(
            payload_state=PayloadState.EXPIRED
        )

        replay = self.ingestion.upload(self.experiment.id, self.submission)

        self.assertEqual(replay.results[0], replace(accepted.results[0], created=False))
        refreshed_item = OfflineExperimentItem.objects.for_team(self.team.id).get(id=item.id)
        refreshed_result = OfflineEvaluationResult.objects.for_team(self.team.id).get(id=result.id)
        self.assertEqual(refreshed_item.payload_expires_at, item.payload_expires_at)
        self.assertEqual(refreshed_result.payload_expires_at, result.payload_expires_at)
        self.assertEqual(refreshed_item.payload_state, PayloadState.EXPIRED)
        self.assertEqual(refreshed_result.payload_state, PayloadState.EXPIRED)
        self.assertFalse(OfflineExperimentItemPayload.objects.for_team(self.team.id).exists())
        self.assertFalse(OfflineEvaluationResultPayload.objects.for_team(self.team.id).exists())

    def test_previous_archived_version_uses_its_own_configuration(self) -> None:
        self.scorer.create_new_version(config={"min": 10, "max": 20}, created_by=None)
        self.scorer.archived = True
        self.scorer.save(update_fields=["archived"])

        receipt = self.ingestion.upload(self.experiment.id, self.submission)

        result = OfflineEvaluationResult.objects.for_team(self.team.id).get(id=receipt.results[0].id)
        self.assertEqual(result.scorer_version_id, self.version.id)
        self.assertEqual(result.numeric_value, 0.8)

    def test_dataset_snapshot_membership_and_retry_after_dataset_deletion(self) -> None:
        dataset = Dataset.objects.for_team(self.team.id).create(team=self.team, name="Examples")
        first_revision = DatasetRevision.objects.for_team(self.team.id).create(
            team=self.team, dataset=dataset, revision=1
        )
        second_revision = DatasetRevision.objects.for_team(self.team.id).create(
            team=self.team, dataset=dataset, revision=2
        )
        dataset_item = DatasetItem.objects.for_team(self.team.id).create(team=self.team, dataset=dataset)
        old_version = DatasetItemVersion.objects.for_team(self.team.id).create(
            team=self.team,
            dataset=dataset,
            dataset_item=dataset_item,
            dataset_revision=first_revision,
            version=1,
            input={"question": "The original question"},
        )
        new_version = DatasetItemVersion.objects.for_team(self.team.id).create(
            team=self.team,
            dataset=dataset,
            dataset_item=dataset_item,
            dataset_revision=second_revision,
            version=2,
            input={"question": "A new question"},
        )
        experiment_submission = replace(self.experiment_submission, id=uuid4(), dataset_revision_id=first_revision.id)
        experiment = self.lifecycle.create(experiment_submission).experiment
        submission = replace(self.submission, items=[replace(self.item, dataset_item_version_id=old_version.id)])
        with self.assertRaises(OfflineEvaluationValidationError):
            self.ingestion.upload(
                experiment.id, replace(submission, items=[replace(self.item, dataset_item_version_id=new_version.id)])
            )
        receipt = self.ingestion.upload(experiment.id, submission)
        self.assertEqual(experiment.dataset_source, "posthog")
        self.assertEqual(experiment.dataset_identifier, str(dataset.id))
        item = OfflineExperimentItem.objects.for_team(self.team.id).get(id=self.item.id)
        self.assertEqual(item.dataset_item_identifier, str(dataset_item.id))
        self.assertEqual(item.dataset_item_version_identifier, str(old_version.id))
        self.assertEqual(
            OfflineExperimentItemPayload.objects.for_team(self.team.id).get(item=item).data, self.item.payload
        )

        dataset.delete()

        replay_experiment = self.lifecycle.create(experiment_submission).experiment
        replay_upload = self.ingestion.upload(experiment.id, submission)
        self.assertIsNone(replay_experiment.dataset_revision_id)
        self.assertEqual(replay_upload.results[0], replace(receipt.results[0], created=False))
        item.refresh_from_db()
        self.assertIsNone(item.dataset_item_version_id)
        self.assertEqual(item.dataset_item_version_identifier, str(old_version.id))


class TestOfflineEvaluationServiceConcurrency(TransactionTestCase):
    def setUp(self) -> None:
        _, _, self.team = Organization.objects.bootstrap(None)
        self.lifecycle = OfflineExperimentService(team_id=self.team.id)
        self.ingestion = OfflineEvaluationIngestionService(team_id=self.team.id)
        self.experiment = self.lifecycle.create(
            ExperimentSubmission(id=uuid4(), name="Concurrent upload", started_at=timezone.now())
        ).experiment
        scorer = ScoreDefinition.objects.create(team=self.team, name="Accuracy", kind="numeric")
        version = scorer.create_new_version(config={}, created_by=None)
        item = ItemSubmission(id=uuid4())
        self.submission = UploadSubmission(
            items=[item],
            results=[ResultSubmission(item_id=item.id, scorer_version_id=version.id, status="ok", value=0.8)],
        )

    def _run_second_operation(
        self, operation: Callable[[], UploadReceipt | ExperimentReceipt], started: Event
    ) -> UploadReceipt | ExperimentReceipt:
        def observe_query(
            execute: Callable[..., object], sql: str, params: object, many: bool, context: object
        ) -> object:
            if sql.startswith("SELECT") and OfflineExperiment._meta.db_table in sql:
                started.set()
            return execute(sql, params, many, context)

        try:
            with connection.execute_wrapper(observe_query):
                return operation()
        finally:
            connection.close()

    def test_concurrent_duplicate_uploads_return_the_same_result(self) -> None:
        second_started = Event()
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                first = self.ingestion.upload(self.experiment.id, self.submission)
                pending = executor.submit(
                    self._run_second_operation,
                    lambda: self.ingestion.upload(self.experiment.id, self.submission),
                    second_started,
                )
                self.assertTrue(second_started.wait(timeout=10))
            second = pending.result(timeout=10)

        assert isinstance(second, UploadReceipt)
        self.assertEqual(second.results, [replace(first.results[0], created=False)])
        self.assertEqual(OfflineEvaluationResult.objects.for_team(self.team.id).count(), 1)

    def test_concurrent_experiment_creation_returns_one_identity(self) -> None:
        submission = ExperimentSubmission(id=uuid4(), name="Retried creation", started_at=timezone.now())
        second_started = Event()
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                first = self.lifecycle.create(submission)
                pending = executor.submit(
                    self._run_second_operation,
                    lambda: self.lifecycle.create(submission),
                    second_started,
                )
                self.assertTrue(second_started.wait(timeout=10))
            second = pending.result(timeout=10)

        assert isinstance(second, ExperimentReceipt)
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.experiment.id, second.experiment.id)
        self.assertEqual(first.experiment.created_at, second.experiment.created_at)
        self.assertEqual(OfflineExperiment.objects.for_team(self.team.id).filter(id=submission.id).count(), 1)

    @parameterized.expand([("upload_first",), ("complete_first",)])
    def test_upload_and_completion_serialize(self, first_operation: str) -> None:
        second_started = Event()
        operation: Callable[[], UploadReceipt | ExperimentReceipt]
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                if first_operation == "upload_first":
                    self.ingestion.upload(self.experiment.id, self.submission)
                    operation = lambda: self.lifecycle.close(self.experiment.id, status="completed")
                else:
                    self.lifecycle.close(self.experiment.id, status="completed")
                    operation = lambda: self.ingestion.upload(self.experiment.id, self.submission)
                pending = executor.submit(self._run_second_operation, operation, second_started)
                self.assertTrue(second_started.wait(timeout=10))

            if first_operation == "upload_first":
                closed = pending.result(timeout=10)
                assert isinstance(closed, ExperimentReceipt)
                self.assertEqual(closed.counts.accepted_result_count, 1)
            else:
                with self.assertRaises(OfflineEvaluationConflict) as error:
                    pending.result(timeout=10)
                self.assertEqual(error.exception.code, "experiment_closed")
                self.assertFalse(OfflineEvaluationResult.objects.for_team(self.team.id).exists())
        self.experiment.refresh_from_db()
        self.assertEqual(self.experiment.status, "completed")
