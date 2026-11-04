from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Event
from typing import Literal
from uuid import uuid4

import time_machine
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.scoping.manager import TeamScopedQuerySet

from products.ai_observability.backend.models.datasets import Dataset, DatasetItem, DatasetItemVersion, DatasetRevision
from products.ai_observability.backend.models.offline_evaluations import (
    OfflineEvaluationResult,
    OfflineEvaluationResultPayload,
    OfflineEvaluationUsageLedger,
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
from products.ai_observability.backend.offline_payload_retention import OfflinePayloadRetention
from products.ai_observability.backend.tasks.offline_payload_retention import expire_offline_evaluation_payloads


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
        self.lifecycle = OfflineExperimentService(team_id=self.team.id, user_access_control=None)
        self.ingestion = OfflineEvaluationIngestionService(team_id=self.team.id, user_access_control=None)
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

    @parameterized.expand([(None,), ("model-a",)])
    def test_upload_retry_preserves_identity_acceptance_and_retention(self, model_version: str | None) -> None:
        self.item = replace(self.item, model_version=model_version)
        self.submission = replace(self.submission, items=[self.item])
        accepted = self.ingestion.upload(self.experiment.id, self.submission)
        replay = self.ingestion.upload(self.experiment.id, self.submission)

        self.assertEqual(replay.items, [replace(accepted.items[0], created=False)])
        self.assertEqual(replay.results, [replace(accepted.results[0], created=False)])
        self.assertTrue(accepted.items[0].created)
        self.assertTrue(accepted.results[0].created)
        item = OfflineExperimentItem.objects.for_team(self.team.id).get(id=self.item.id)
        result = OfflineEvaluationResult.objects.for_team(self.team.id).get(id=accepted.results[0].id)
        self.assertEqual(item.model_version, model_version)
        self.assertEqual(item.payload_expires_at, item.accepted_at + timedelta(days=30))
        self.assertEqual(result.payload_expires_at, result.accepted_at + timedelta(days=30))
        self.assertEqual(
            OfflineExperimentItemPayload.objects.for_team(self.team.id).get(item=item).data, self.item.payload
        )
        self.assertEqual(
            OfflineEvaluationResultPayload.objects.for_team(self.team.id).get(result=result).data, self.result.payload
        )
        ledger = OfflineEvaluationUsageLedger.objects.for_team(self.team.id).get()
        self.assertEqual(ledger.quantity, 1)
        self.assertEqual(ledger.accepted_at, result.accepted_at)

    def test_upload_records_one_usage_entry_for_all_new_results_including_non_ok_outcomes(self) -> None:
        second_item = replace(self.item, id=uuid4())
        second_version = self.scorer.create_new_version(config={}, created_by=None)
        submission = UploadSubmission(
            items=[self.item, second_item],
            results=[
                self.result,
                replace(self.result, scorer_version_id=second_version.id, status="error", value=None),
                replace(self.result, item_id=second_item.id, status="skipped", value=None),
                replace(
                    self.result,
                    item_id=second_item.id,
                    scorer_version_id=second_version.id,
                    status="not_applicable",
                    value=None,
                ),
            ],
        )

        accepted = self.ingestion.upload(self.experiment.id, submission)

        ledger = OfflineEvaluationUsageLedger.objects.for_team(self.team.id).get()
        self.assertEqual(ledger.quantity, 4)
        self.assertEqual(ledger.organization_id, self.team.organization_id)
        self.assertEqual(ledger.experiment_id, self.experiment.id)
        self.assertEqual({result.accepted_at for result in accepted.results}, {ledger.accepted_at})
        self.assertEqual(
            set(OfflineEvaluationResult.objects.for_team(self.team.id).values_list("accepted_at", flat=True)),
            {ledger.accepted_at},
        )
        self.assertTrue(timezone.is_aware(ledger.accepted_at))

        for result in reversed(submission.results):
            replay = self.ingestion.upload(self.experiment.id, UploadSubmission(results=[result]))
            self.assertFalse(replay.results[0].created)
        self.assertEqual(OfflineEvaluationUsageLedger.objects.for_team(self.team.id).get().quantity, 4)

    def test_ledger_write_failure_rolls_back_results_and_payloads(self) -> None:
        def fail_ledger_insert(
            execute: Callable[..., object], sql: str, params: object, many: bool, context: object
        ) -> object:
            if sql.startswith("INSERT INTO") and OfflineEvaluationUsageLedger._meta.db_table in sql:
                raise IntegrityError("Ledger insert failed")
            return execute(sql, params, many, context)

        with (
            connection.execute_wrapper(fail_ledger_insert),
            self.assertRaisesMessage(IntegrityError, "Ledger insert failed"),
        ):
            self.ingestion.upload(self.experiment.id, self.submission)

        self.assertFalse(OfflineExperimentItem.objects.for_team(self.team.id).exists())
        self.assertFalse(OfflineEvaluationResult.objects.for_team(self.team.id).exists())
        self.assertFalse(OfflineExperimentItemPayload.objects.for_team(self.team.id).exists())
        self.assertFalse(OfflineEvaluationResultPayload.objects.for_team(self.team.id).exists())
        self.assertFalse(OfflineEvaluationUsageLedger.objects.for_team(self.team.id).exists())
        accepted = self.ingestion.upload(self.experiment.id, self.submission)
        self.assertTrue(accepted.results[0].created)
        self.assertEqual(OfflineEvaluationUsageLedger.objects.for_team(self.team.id).get().quantity, 1)

    def test_usage_keeps_organization_at_acceptance_after_project_moves(self) -> None:
        self.ingestion.upload(self.experiment.id, self.submission)
        original_ledger = OfflineEvaluationUsageLedger.objects.for_team(self.team.id).get()
        other_organization = Organization.objects.create(name="New owner")
        project = self.team.project
        project.organization = other_organization
        project.save(update_fields=["organization"])
        Team.objects.filter(id=self.team.id).update(organization=other_organization)
        second_item = replace(self.item, id=uuid4())

        self.ingestion.upload(
            self.experiment.id,
            UploadSubmission(items=[second_item], results=[self.result, replace(self.result, item_id=second_item.id)]),
        )

        original_ledger.refresh_from_db()
        self.assertEqual(original_ledger.organization_id, self.team.organization_id)
        self.assertEqual(original_ledger.quantity, 1)
        new_ledger = OfflineEvaluationUsageLedger.objects.for_team(self.team.id).exclude(id=original_ledger.id).get()
        self.assertEqual(new_ledger.organization_id, other_organization.id)
        self.assertEqual(new_ledger.quantity, 1)

    def test_privileged_result_deletion_removes_retry_identity_but_not_recorded_usage(self) -> None:
        self.ingestion.upload(self.experiment.id, self.submission)
        OfflineEvaluationResult.objects.for_team(self.team.id).all().delete()
        replay = self.ingestion.upload(self.experiment.id, self.submission)
        self.assertTrue(replay.results[0].created)
        self.assertEqual(
            list(OfflineEvaluationUsageLedger.objects.for_team(self.team.id).values_list("quantity", flat=True)),
            [1, 1],
        )

    def test_child_environment_keeps_the_entire_experiment_graph_and_hosted_links(self) -> None:
        child = Team.objects.create(organization=self.team.organization, parent_team=self.team)
        lifecycle = OfflineExperimentService(team_id=child.id, user_access_control=None)
        ingestion = OfflineEvaluationIngestionService(team_id=child.id, user_access_control=None)
        scorer = ScoreDefinition.objects.create(team=child, name="Child accuracy", kind="numeric")
        version = scorer.create_new_version(config={"min": 0, "max": 1}, created_by=None)
        dataset = Dataset.objects.for_team(child.id, canonical=True).create(team=child, name="Child examples")
        revision = DatasetRevision.objects.for_team(child.id, canonical=True).create(
            team=child, dataset=dataset, revision=1
        )
        dataset_item = DatasetItem.objects.for_team(child.id, canonical=True).create(team=child, dataset=dataset)
        item_version = DatasetItemVersion.objects.for_team(child.id, canonical=True).create(
            team=child, dataset=dataset, dataset_item=dataset_item, dataset_revision=revision, version=1, input={}
        )
        experiment = lifecycle.create(
            replace(self.experiment_submission, id=uuid4(), dataset_revision_id=revision.id)
        ).experiment
        accepted = ingestion.upload(
            experiment.id,
            UploadSubmission(
                items=[replace(self.item, dataset_item_version_id=item_version.id)],
                results=[replace(self.result, scorer_version_id=version.id)],
            ),
        )
        closed = lifecycle.close(experiment.id, status="completed")

        self.assertEqual(closed.counts.accepted_item_count, 1)
        self.assertEqual(closed.counts.accepted_result_count, 1)
        ledger = OfflineEvaluationUsageLedger.objects.for_team(child.id).get()
        self.assertEqual(ledger.organization_id, child.organization_id)
        self.assertEqual(ledger.quantity, 1)
        for model, row_id in (
            (OfflineExperiment, experiment.id),
            (OfflineExperimentItem, self.item.id),
            (OfflineEvaluationResult, accepted.results[0].id),
            (OfflineExperimentItemPayload, self.item.id),
            (OfflineEvaluationResultPayload, accepted.results[0].id),
            (OfflineEvaluationUsageLedger, ledger.id),
        ):
            with self.subTest(model=model.__name__):
                row = model.objects.for_team(child.id).get(pk=row_id)
                row.save()
                row.refresh_from_db()
                self.assertEqual(row.team_id, child.id)
                self.assertFalse(model.objects.for_team(self.team.id).filter(pk=row_id).exists())

        with self.assertRaises(OfflineEvaluationNotFound):
            lifecycle.close(self.experiment.id, status="completed")
        with self.assertRaises(OfflineEvaluationNotFound):
            self.lifecycle.close(experiment.id, status="completed")
        self.experiment.refresh_from_db()
        self.assertEqual(self.experiment.team_id, self.team.id)

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
        self.assertEqual(OfflineEvaluationUsageLedger.objects.for_team(self.team.id).get().quantity, 1)

    @parameterized.expand([("missing_scorer",), ("foreign_scorer",), ("invalid_score",), ("missing_item_and_scorer",)])
    def test_invalid_batch_does_not_persist_any_rows(self, failure: str) -> None:
        second_item = replace(self.item, id=uuid4())
        second_result = replace(self.result, item_id=second_item.id)
        third_item = replace(self.item, id=uuid4())
        third_result = replace(self.result, item_id=third_item.id, value=-1.0)
        expected_fields = {"results.2.value"}
        if failure == "missing_scorer":
            second_result = replace(second_result, scorer_version_id=uuid4())
            expected_fields.add("results.1.scorer_version_id")
        elif failure == "foreign_scorer":
            second_result = replace(second_result, scorer_version_id=self.other_version.id)
            expected_fields.add("results.1.scorer_version_id")
        elif failure == "missing_item_and_scorer":
            second_result = replace(second_result, item_id=uuid4(), scorer_version_id=uuid4())
            expected_fields.update({"results.1.item_id", "results.1.scorer_version_id"})
        else:
            second_result = replace(second_result, value=2.0)
            expected_fields.add("results.1.value")

        with self.assertRaises(OfflineEvaluationValidationError) as error:
            self.ingestion.upload(
                self.experiment.id,
                UploadSubmission(
                    items=[self.item, second_item, third_item], results=[self.result, second_result, third_result]
                ),
            )
        self.assertTrue(error.exception.field.startswith("results.1."))
        self.assertEqual(set(error.exception.errors), expected_fields)
        self.assertFalse(OfflineExperimentItem.objects.for_team(self.team.id).exists())
        self.assertFalse(OfflineEvaluationResult.objects.for_team(self.team.id).exists())
        self.assertFalse(OfflineExperimentItemPayload.objects.for_team(self.team.id).exists())
        self.assertFalse(OfflineEvaluationResultPayload.objects.for_team(self.team.id).exists())
        self.assertFalse(OfflineEvaluationUsageLedger.objects.for_team(self.team.id).exists())

    def test_mixed_upload_counts_new_results_and_reuses_existing_items(self) -> None:
        self.ingestion.upload(self.experiment.id, self.submission)
        scorer = ScoreDefinition.objects.create(team=self.team, name="Safety", kind="boolean")
        version = scorer.create_new_version(config={}, created_by=None)
        second_item = replace(self.item, id=uuid4())

        receipt = self.ingestion.upload(
            self.experiment.id,
            UploadSubmission(
                items=[second_item],
                results=[
                    ResultSubmission(item_id=self.item.id, scorer_version_id=version.id, status="ok", value=False),
                    self.result,
                    replace(self.result, item_id=second_item.id),
                ],
            ),
        )

        self.assertFalse(receipt.items[0].created)
        self.assertTrue(receipt.results[0].created)
        self.assertFalse(receipt.results[1].created)
        self.assertTrue(receipt.results[2].created)
        self.assertEqual(OfflineExperimentItem.objects.for_team(self.team.id).count(), 2)
        self.assertEqual(OfflineExperimentItemPayload.objects.for_team(self.team.id).count(), 2)
        self.assertEqual(OfflineEvaluationResult.objects.for_team(self.team.id).count(), 3)
        self.assertIs(
            OfflineEvaluationResult.objects.for_team(self.team.id).get(id=receipt.results[0].id).boolean_value, False
        )
        self.assertEqual(
            sorted(OfflineEvaluationUsageLedger.objects.for_team(self.team.id).values_list("quantity", flat=True)),
            [1, 2],
        )

    @parameterized.expand([("unknown",), ("foreign",)])
    def test_inaccessible_experiment_is_not_found_for_upload_and_close(self, target: str) -> None:
        experiment_id = uuid4() if target == "unknown" else self.experiment.id
        team_id = self.team.id if target == "unknown" else self.other_team.id
        with self.assertRaises(OfflineEvaluationNotFound):
            OfflineEvaluationIngestionService(team_id=team_id, user_access_control=None).upload(
                experiment_id, self.submission
            )
        with self.assertRaises(OfflineEvaluationNotFound):
            OfflineExperimentService(team_id=team_id, user_access_control=None).close(experiment_id, status="failed")

    @parameterized.expand([("unknown",), ("other_experiment",), ("other_project",)])
    def test_result_cannot_reference_an_item_outside_its_experiment(self, target: str) -> None:
        if target != "unknown":
            self.ingestion.upload(self.experiment.id, self.submission)
        team_id = self.other_team.id if target == "other_project" else self.team.id
        experiment = (
            OfflineExperimentService(team_id=team_id, user_access_control=None)
            .create(replace(self.experiment_submission, id=uuid4()))
            .experiment
        )
        result = (
            replace(self.result, scorer_version_id=self.other_version.id) if target == "other_project" else self.result
        )

        with self.assertRaises(OfflineEvaluationValidationError) as error:
            OfflineEvaluationIngestionService(team_id=team_id, user_access_control=None).upload(
                experiment.id, UploadSubmission(results=[result])
            )
        self.assertEqual(error.exception.field, "results.0.item_id")

    @parameterized.expand([("experiment",), ("item",)])
    def test_global_uuid_collision_returns_a_controlled_conflict(self, target: str) -> None:
        other_lifecycle = OfflineExperimentService(team_id=self.other_team.id, user_access_control=None)
        if target == "experiment":
            with self.assertRaises(OfflineEvaluationConflict) as error:
                other_lifecycle.create(self.experiment_submission)
        else:
            self.ingestion.upload(self.experiment.id, self.submission)
            other_experiment = other_lifecycle.create(replace(self.experiment_submission, id=uuid4())).experiment
            with self.assertRaises(OfflineEvaluationConflict) as error:
                OfflineEvaluationIngestionService(team_id=self.other_team.id, user_access_control=None).upload(
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
        with time_machine.travel(item.payload_expires_at, tick=False):
            OfflinePayloadRetention().run()

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
        self.assertEqual(OfflineEvaluationUsageLedger.objects.for_team(self.team.id).count(), 1)

    @parameterized.expand([(-1, 0), (0, 2), (1, 2)])
    def test_retention_boundary_and_run_event(self, seconds: int, expected: int) -> None:
        receipt = self.ingestion.upload(self.experiment.id, self.submission)
        experiment_before = OfflineExperiment.objects.for_team(self.team.id).values().get()
        item_before = OfflineExperimentItem.objects.for_team(self.team.id).values().get()
        result_before = OfflineEvaluationResult.objects.for_team(self.team.id).values().get()
        ledger_before = OfflineEvaluationUsageLedger.objects.for_team(self.team.id).values().get()
        with (
            time_machine.travel(receipt.items[0].accepted_at + timedelta(days=30, seconds=seconds), tick=False),
            patch("products.ai_observability.backend.tasks.offline_payload_retention.ph_scoped_capture") as scoped,
        ):
            expire_offline_evaluation_payloads()
            properties = scoped.return_value.__enter__.return_value.call_args.kwargs["properties"]
            self.assertEqual(properties["payloads_expired"], expected)
            self.assertEqual(properties["batches"], expected)
            self.assertEqual(properties["status"], "completed")
            self.assertEqual(OfflineExperimentItemPayload.objects.for_team(self.team.id).count(), 1 - expected // 2)
            self.assertEqual(OfflineEvaluationResultPayload.objects.for_team(self.team.id).count(), 1 - expected // 2)
            expire_offline_evaluation_payloads()
            self.assertEqual(
                scoped.return_value.__enter__.return_value.call_args.kwargs["properties"]["payloads_expired"], 0
            )
        if expected:
            item_before["payload_state"] = PayloadState.EXPIRED
            result_before["payload_state"] = PayloadState.EXPIRED
        self.assertEqual(OfflineExperiment.objects.for_team(self.team.id).values().get(), experiment_before)
        self.assertEqual(OfflineExperimentItem.objects.for_team(self.team.id).values().get(), item_before)
        self.assertEqual(OfflineEvaluationResult.objects.for_team(self.team.id).values().get(), result_before)
        self.assertEqual(OfflineEvaluationUsageLedger.objects.for_team(self.team.id).values().get(), ledger_before)

    def test_retention_preserves_recent_payloads_and_items_without_payloads(self) -> None:
        now = timezone.now()
        old_item = replace(self.item, id=uuid4())
        absent_item = replace(self.item, id=uuid4(), payload=None)
        with time_machine.travel(now - timedelta(days=31), tick=False):
            self.ingestion.upload(
                self.experiment.id,
                UploadSubmission(
                    items=[old_item, absent_item],
                    results=[
                        replace(self.result, item_id=old_item.id),
                        replace(self.result, item_id=absent_item.id, payload=None),
                    ],
                ),
            )
        self.ingestion.upload(self.experiment.id, self.submission)

        sweep = OfflinePayloadRetention()
        sweep.run()

        self.assertEqual((sweep.item_payloads_expired, sweep.result_payloads_expired), (1, 1))
        self.assertEqual(
            OfflineExperimentItemPayload.objects.for_team(self.team.id).values_list("item_id", "data").get(),
            (self.item.id, self.item.payload),
        )
        self.assertEqual(
            OfflineEvaluationResultPayload.objects.for_team(self.team.id).values_list("result__item_id", "data").get(),
            (self.item.id, self.result.payload),
        )
        self.assertEqual(
            dict(OfflineExperimentItem.objects.for_team(self.team.id).values_list("id", "payload_state")),
            {old_item.id: "expired", absent_item.id: "not_provided", self.item.id: "available"},
        )
        self.assertEqual(
            dict(OfflineEvaluationResult.objects.for_team(self.team.id).values_list("item_id", "payload_state")),
            {old_item.id: "expired", absent_item.id: "not_provided", self.item.id: "available"},
        )

    @parameterized.expand([("item",), ("result",)])
    def test_retention_rolls_back_payload_deletion_and_reports_failure(self, failing_owner: str) -> None:
        receipt = self.ingestion.upload(self.experiment.id, self.submission)
        failing_model = OfflineExperimentItem if failing_owner == "item" else OfflineEvaluationResult
        original_update = TeamScopedQuerySet.update

        def fail_state_update(
            queryset: TeamScopedQuerySet[OfflineExperimentItem | OfflineEvaluationResult], **kwargs: object
        ) -> int:
            if queryset.model is failing_model:
                raise RuntimeError("write failed")
            return original_update(queryset, **kwargs)

        with (
            time_machine.travel(receipt.items[0].accepted_at + timedelta(days=30), tick=False),
            patch("products.ai_observability.backend.tasks.offline_payload_retention.ph_scoped_capture") as scoped,
        ):
            with (
                patch.object(TeamScopedQuerySet, "update", autospec=True, side_effect=fail_state_update),
                self.assertRaisesMessage(RuntimeError, "write failed"),
            ):
                expire_offline_evaluation_payloads()
            properties = scoped.return_value.__enter__.return_value.call_args.kwargs["properties"]
            self.assertEqual(properties["status"], "failed")
            committed = int(failing_owner == "result")
            self.assertEqual(properties["batches"], committed)
            self.assertEqual(properties["payloads_expired"], committed)
            self.assertEqual(OfflineExperimentItemPayload.objects.for_team(self.team.id).exists(), not committed)
            self.assertTrue(OfflineEvaluationResultPayload.objects.for_team(self.team.id).exists())
            self.assertEqual(failing_model.objects.for_team(self.team.id).get().payload_state, PayloadState.AVAILABLE)
            expire_offline_evaluation_payloads()
            retry = scoped.return_value.__enter__.return_value.call_args.kwargs["properties"]
            self.assertEqual(retry["status"], "completed")
            self.assertEqual(retry["payloads_expired"], 2 - committed)
        self.assertFalse(OfflineExperimentItemPayload.objects.for_team(self.team.id).exists())
        self.assertFalse(OfflineEvaluationResultPayload.objects.for_team(self.team.id).exists())

    @parameterized.expand([([0, 180], 0), ([0, 0, 0, 180], 1)])
    def test_retention_time_budget_leaves_remaining_payloads(self, clock: list[int], expired_items: int) -> None:
        receipt = self.ingestion.upload(self.experiment.id, self.submission)
        with (
            time_machine.travel(receipt.items[0].accepted_at + timedelta(days=30), tick=False),
            patch("products.ai_observability.backend.offline_payload_retention.time") as mocked_time,
        ):
            mocked_time.monotonic.side_effect = clock
            sweep = OfflinePayloadRetention()
            sweep.run()
        self.assertTrue(sweep.budget_exhausted)
        self.assertEqual((sweep.item_payloads_expired, sweep.result_payloads_expired), (expired_items, 0))
        self.assertEqual(OfflineExperimentItemPayload.objects.for_team(self.team.id).count(), 1 - expired_items)
        self.assertEqual(OfflineEvaluationResultPayload.objects.for_team(self.team.id).count(), 1)

    def test_retention_batch_limit_leaves_work_for_next_run(self) -> None:
        for _ in range(2):
            item = replace(self.item, id=uuid4())
            self.ingestion.upload(
                self.experiment.id, UploadSubmission(items=[item], results=[replace(self.result, item_id=item.id)])
            )
        with (
            time_machine.travel(timezone.now() + timedelta(days=31), tick=False),
            patch("products.ai_observability.backend.offline_payload_retention.BATCH_SIZE", 1),
            patch("products.ai_observability.backend.offline_payload_retention.MAX_BATCHES_PER_TYPE", 1),
        ):
            sweep = OfflinePayloadRetention()
            sweep.run()
            self.assertTrue(sweep.budget_exhausted)
            self.assertEqual((sweep.item_payloads_expired, sweep.result_payloads_expired), (1, 1))
            self.assertEqual(OfflineExperimentItemPayload.objects.for_team(self.team.id).count(), 1)
            OfflinePayloadRetention().run()
            self.assertFalse(OfflineExperimentItemPayload.objects.for_team(self.team.id).exists())

    def test_retention_checks_time_budget_between_environments(self) -> None:
        now = timezone.now()
        with time_machine.travel(now - timedelta(days=32), tick=False):
            self.ingestion.upload(self.experiment.id, self.submission)
        other_experiment = (
            OfflineExperimentService(team_id=self.other_team.id, user_access_control=None)
            .create(replace(self.experiment_submission, id=uuid4()))
            .experiment
        )
        item = replace(self.item, id=uuid4())
        with time_machine.travel(now - timedelta(days=31), tick=False):
            OfflineEvaluationIngestionService(team_id=self.other_team.id, user_access_control=None).upload(
                other_experiment.id,
                UploadSubmission(
                    items=[item],
                    results=[replace(self.result, item_id=item.id, scorer_version_id=self.other_version.id)],
                ),
            )
        sweep = OfflinePayloadRetention()
        with patch("products.ai_observability.backend.offline_payload_retention.time") as mocked_time:
            mocked_time.monotonic.side_effect = lambda: 180 if sweep.batches else 0
            sweep.run()

        self.assertTrue(sweep.budget_exhausted)
        self.assertEqual((sweep.batches, sweep.item_payloads_expired, sweep.result_payloads_expired), (1, 1, 0))
        self.assertFalse(OfflineExperimentItemPayload.objects.for_team(self.team.id).exists())
        self.assertTrue(OfflineExperimentItemPayload.objects.for_team(self.other_team.id).exists())
        self.assertEqual(
            OfflineExperimentItem.objects.for_team(self.other_team.id).get().payload_state, PayloadState.AVAILABLE
        )
        for team_id in (self.team.id, self.other_team.id):
            self.assertTrue(OfflineEvaluationResultPayload.objects.for_team(team_id).exists())

        retry = OfflinePayloadRetention()
        retry.run()
        self.assertEqual((retry.batches, retry.item_payloads_expired, retry.result_payloads_expired), (3, 1, 2))
        for team_id in (self.team.id, self.other_team.id):
            self.assertFalse(OfflineExperimentItemPayload.objects.for_team(team_id).exists())
            self.assertFalse(OfflineEvaluationResultPayload.objects.for_team(team_id).exists())

    @parameterized.expand([(0,), (31,)])
    def test_retention_keeps_environment_scoping(self, child_age_days: int) -> None:
        now = timezone.now()
        with time_machine.travel(now - timedelta(days=31), tick=False):
            self.ingestion.upload(self.experiment.id, self.submission)
        child = Team.objects.create(organization=self.team.organization, parent_team=self.team)
        scorer = ScoreDefinition.objects.create(team=child, name="Child accuracy", kind="numeric")
        version = scorer.create_new_version(config={}, created_by=None)
        child_experiment = (
            OfflineExperimentService(team_id=child.id, user_access_control=None)
            .create(replace(self.experiment_submission, id=uuid4()))
            .experiment
        )
        item = replace(self.item, id=uuid4())
        with time_machine.travel(now - timedelta(days=child_age_days), tick=False):
            OfflineEvaluationIngestionService(team_id=child.id, user_access_control=None).upload(
                child_experiment.id,
                UploadSubmission(
                    items=[item], results=[replace(self.result, item_id=item.id, scorer_version_id=version.id)]
                ),
            )
        sweep = OfflinePayloadRetention()
        sweep.run()
        expired = 1 + int(child_age_days == 31)
        self.assertEqual((sweep.item_payloads_expired, sweep.result_payloads_expired), (expired, expired))
        self.assertEqual(sweep.batches, 2 * expired)
        for team_id in (self.team.id, child.id):
            retained = team_id == child.id and child_age_days == 0
            self.assertEqual(OfflineExperimentItemPayload.objects.for_team(team_id).exists(), retained)
            self.assertEqual(OfflineEvaluationResultPayload.objects.for_team(team_id).exists(), retained)
            self.assertEqual(OfflineEvaluationResult.objects.for_team(team_id).count(), 1)

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
        second_item = replace(
            self.item,
            id=uuid4(),
            dataset_item_version_id=old_version.id,
            dataset_item_identifier="wrong-item",
            dataset_item_version_identifier="wrong-version",
        )
        with self.assertRaises(OfflineEvaluationValidationError) as error:
            self.ingestion.upload(
                experiment.id,
                replace(
                    submission,
                    items=[replace(self.item, dataset_item_version_id=new_version.id), second_item],
                    results=[self.result, replace(self.result, item_id=second_item.id, value=2.0)],
                ),
            )
        self.assertEqual(
            set(error.exception.errors),
            {
                "items.0.dataset_item_version_id",
                "items.1.dataset_item_identifier",
                "items.1.dataset_item_version_identifier",
                "results.1.value",
            },
        )
        self.assertFalse(OfflineExperimentItem.objects.for_team(self.team.id).exists())
        self.assertFalse(OfflineEvaluationResult.objects.for_team(self.team.id).exists())
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
        self.lifecycle = OfflineExperimentService(team_id=self.team.id, user_access_control=None)
        self.ingestion = OfflineEvaluationIngestionService(team_id=self.team.id, user_access_control=None)
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

    def _run_retention(self) -> OfflinePayloadRetention:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '2s'")
            sweep = OfflinePayloadRetention()
            sweep.run()
            return sweep
        finally:
            connection.close()

    @parameterized.expand([("item",), ("result",)])
    def test_retention_skips_locked_payload_owners_and_recovers_on_next_run(self, locked_type: str) -> None:
        with time_machine.travel(timezone.now() - timedelta(days=31), tick=False):
            for _ in range(2):
                item = replace(self.submission.items[0], id=uuid4(), payload={"input": "Example"})
                self.ingestion.upload(
                    self.experiment.id,
                    UploadSubmission(
                        items=[item],
                        results=[
                            replace(self.submission.results[0], item_id=item.id, payload={"reasoning": "Example"})
                        ],
                    ),
                )
        owner_model = OfflineExperimentItem if locked_type == "item" else OfflineEvaluationResult
        payload_model = OfflineExperimentItemPayload if locked_type == "item" else OfflineEvaluationResultPayload
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                locked = owner_model.objects.for_team(self.team.id).select_for_update().order_by("id").first()
                assert locked is not None
                sweep = executor.submit(self._run_retention).result(timeout=10)
                self.assertEqual(
                    (sweep.item_payloads_expired, sweep.result_payloads_expired),
                    (1, 2) if locked_type == "item" else (2, 1),
                )
                self.assertTrue(payload_model.objects.for_team(self.team.id).filter(pk=locked.pk).exists())
                locked.refresh_from_db()
                self.assertEqual(locked.payload_state, PayloadState.AVAILABLE)
            retry = executor.submit(self._run_retention).result(timeout=10)
        self.assertEqual(
            (retry.item_payloads_expired, retry.result_payloads_expired),
            (1, 0) if locked_type == "item" else (0, 1),
        )
        self.assertFalse(OfflineExperimentItemPayload.objects.for_team(self.team.id).exists())
        self.assertFalse(OfflineEvaluationResultPayload.objects.for_team(self.team.id).exists())
        self.assertEqual(OfflineExperimentItem.objects.for_team(self.team.id).count(), 2)
        self.assertEqual(OfflineEvaluationResult.objects.for_team(self.team.id).count(), 2)
        self.assertEqual(OfflineEvaluationUsageLedger.objects.for_team(self.team.id).count(), 2)

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

    @parameterized.expand([(False,), (True,)])
    def test_concurrent_duplicate_uploads_return_the_same_result(self, overlapping: bool) -> None:
        second_submission = self.submission
        if overlapping:
            new_item = replace(self.submission.items[0], id=uuid4())
            second_submission = UploadSubmission(
                items=[new_item],
                results=[replace(self.submission.results[0], item_id=new_item.id), self.submission.results[0]],
            )
        second_started = Event()
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                first = self.ingestion.upload(self.experiment.id, self.submission)
                pending = executor.submit(
                    self._run_second_operation,
                    lambda: self.ingestion.upload(self.experiment.id, second_submission),
                    second_started,
                )
                self.assertTrue(second_started.wait(timeout=10))
            second = pending.result(timeout=10)

        assert isinstance(second, UploadReceipt)
        self.assertEqual(second.results[-1], replace(first.results[0], created=False))
        self.assertEqual(OfflineEvaluationResult.objects.for_team(self.team.id).count(), 2 if overlapping else 1)
        self.assertEqual(
            list(OfflineEvaluationUsageLedger.objects.for_team(self.team.id).values_list("quantity", flat=True)),
            [1, 1] if overlapping else [1],
        )

    def test_concurrent_experiment_creation_returns_one_identity(self) -> None:
        submission = ExperimentSubmission(id=uuid4(), name="Retried creation", started_at=self.experiment.started_at)
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
