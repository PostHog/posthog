from dataclasses import replace
from uuid import uuid4

from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team

from products.ai_observability.backend.models.offline_evaluations import (
    OfflineEvaluationResult,
    OfflineEvaluationUsageLedger,
)
from products.ai_observability.backend.models.score_definitions import ScoreDefinition, ScoreDefinitionVersion
from products.ai_observability.backend.offline_evaluation_read_service import OfflineEvaluationReadService
from products.ai_observability.backend.offline_evaluation_read_types import OfflineReadQuery
from products.ai_observability.backend.offline_evaluation_service import (
    OfflineEvaluationConflict,
    OfflineEvaluationIngestionService,
    OfflineEvaluationValidationError,
    OfflineExperimentService,
)
from products.ai_observability.backend.offline_evaluation_types import (
    ExperimentSubmission,
    ItemSubmission,
    ResultStatus,
    ResultSubmission,
    UploadSubmission,
)


class TestCompositeIngestion(TestCase):
    team: Team
    source: ScoreDefinition
    input_version: ScoreDefinitionVersion
    composite: ScoreDefinition
    version: ScoreDefinitionVersion

    @classmethod
    def setUpTestData(cls) -> None:
        _, _, cls.team = Organization.objects.bootstrap(None)
        cls.source = ScoreDefinition.objects.create(team=cls.team, name="Correct", kind="boolean")
        cls.input_version = cls.source.create_new_version(config={"true_is_failure": False}, created_by=None)
        cls.composite = ScoreDefinition.objects.create(
            team=cls.team, name="Overall", kind="numeric", calculation="composite"
        )
        cls.version = cls.composite.create_new_version(
            config={"min": 0, "max": 1},
            composition={
                "expression": "number(correct)",
                "inputs": [{"alias": "correct", "scorer_version_id": str(cls.input_version.id)}],
            },
            created_by=None,
        )

    def setUp(self) -> None:
        self.lifecycle = OfflineExperimentService(team_id=self.team.id, user_access_control=None)
        self.ingestion = OfflineEvaluationIngestionService(
            team_id=self.team.id, user_access_control=None, can_read_results=True
        )
        self.experiment = self.lifecycle.create(
            ExperimentSubmission(id=uuid4(), name="Candidate", started_at=timezone.now())
        ).experiment
        self.item = ItemSubmission(id=uuid4())
        self.source_result = ResultSubmission(
            item_id=self.item.id, scorer_version_id=self.input_version.id, status="ok", value=True
        )
        self.request = ResultSubmission(
            item_id=self.item.id, scorer_version_id=self.version.id, status="ok", calculate=True
        )

    def result(self) -> OfflineEvaluationResult:
        return OfflineEvaluationResult.objects.for_team(self.team.id).get(
            item_id=self.item.id, scorer_version=self.version
        )

    @parameterized.expand([(True,), (False,)])
    def test_same_batch_or_previous_upload_and_closed_retry(self, same_batch: bool) -> None:
        if not same_batch:
            self.ingestion.upload(self.experiment.id, UploadSubmission(items=[self.item], results=[self.source_result]))
        submission = UploadSubmission(
            items=[self.item], results=[self.request, self.source_result] if same_batch else [self.request]
        )
        with patch(
            "products.ai_observability.backend.offline_evaluation_service.is_team_limited", return_value=not same_batch
        ):
            self.ingestion.upload(self.experiment.id, submission)
        derived = self.result()
        self.assertEqual(derived.numeric_value, 1.0)
        source = OfflineEvaluationResult.objects.for_team(self.team.id).get(
            item_id=self.item.id, scorer_version=self.input_version
        )
        self.assertEqual(derived.input_result_ids, [source.id])
        self.assertEqual(
            list(OfflineEvaluationUsageLedger.objects.for_team(self.team.id).values_list("quantity", flat=True)), [1]
        )
        receipt = self.lifecycle.close(self.experiment.id, status="completed")
        self.assertEqual(receipt.counts.accepted_result_count, 2)
        retry = self.ingestion.upload(self.experiment.id, submission)
        self.assertTrue(all(not result.created for result in retry.results))
        self.assertEqual(self.result().id, derived.id)

    def test_missing_input_rejects_atomic_batch_and_requires_exact_version(self) -> None:
        latest = self.source.create_new_version(config={"true_is_failure": True}, created_by=None)
        for results in ([self.request], [self.request, replace(self.source_result, scorer_version_id=latest.id)]):
            with self.assertRaisesMessage(OfflineEvaluationValidationError, "Missing input"):
                self.ingestion.upload(self.experiment.id, UploadSubmission(items=[self.item], results=results))
            self.assertFalse(OfflineEvaluationResult.objects.for_team(self.team.id).exists())

    @parameterized.expand([("error",), ("skipped",), ("not_applicable",)])
    def test_non_success_inputs_propagate_without_fabricated_value(self, status: ResultStatus) -> None:
        self.ingestion.upload(
            self.experiment.id,
            UploadSubmission(
                items=[self.item], results=[replace(self.source_result, status=status, value=None), self.request]
            ),
        )
        self.assertEqual(self.result().status, status)
        self.assertIsNone(self.result().numeric_value)

    @parameterized.expand([("number(correct) / 0",), ("number(correct) * 2",)])
    def test_runtime_or_output_domain_error_preserves_source(self, expression: str) -> None:
        assert self.version.composition is not None
        self.version = self.composite.create_new_version(
            config={"max": 1},
            composition={"expression": expression, "inputs": self.version.composition["inputs"]},
            created_by=None,
        )
        submission = UploadSubmission(
            items=[self.item], results=[self.source_result, replace(self.request, scorer_version_id=self.version.id)]
        )
        receipt = self.ingestion.upload(self.experiment.id, submission)
        self.assertEqual(receipt.results[1].status, "error")
        self.assertEqual(receipt.results[1].error_code, "composite_formula_error")
        retry = self.ingestion.upload(self.experiment.id, submission)
        self.assertEqual(retry.results[1].status, "error")
        self.assertEqual(retry.results[1].error_code, "composite_formula_error")
        self.assertFalse(retry.results[1].created)
        self.assertEqual(self.result().error_code, "composite_formula_error")
        self.assertEqual(OfflineEvaluationResult.objects.for_team(self.team.id).count(), 2)

    def test_composite_ignores_legacy_manual_increment(self) -> None:
        assert self.version.composition is not None
        self.version = self.composite.create_new_version(
            config={"min": 0, "max": 1, "step": 0.5},
            composition={"expression": "number(correct) / 3", "inputs": self.version.composition["inputs"]},
            created_by=None,
        )
        receipt = self.ingestion.upload(
            self.experiment.id,
            UploadSubmission(
                items=[self.item],
                results=[self.source_result, replace(self.request, scorer_version_id=self.version.id)],
            ),
        )
        self.assertEqual(receipt.results[1].status, "ok")
        self.assertIsNone(receipt.results[1].error_code)
        self.assertEqual(self.result().numeric_value, 0.333333333333)

    def test_rejects_supplied_composite_value_and_calculate_for_reported_scorer(self) -> None:
        for result in (
            replace(self.request, calculate=False, value=0.5),
            replace(self.source_result, calculate=True, value=None),
        ):
            with self.assertRaises(OfflineEvaluationValidationError):
                self.ingestion.upload(self.experiment.id, UploadSubmission(items=[self.item], results=[result]))

    @parameterized.expand([('["good", "good"]', "error"), ('["good", "bad"]', "ok")])
    def test_categorical_output_counts_each_item_once(self, categories: str, expected_status: str) -> None:
        composite = ScoreDefinition.objects.create(
            team=self.team, name="Categories", kind="categorical", calculation="composite"
        )
        version = composite.create_new_version(
            config={"selection_mode": "multiple", "options": [{"key": "good"}, {"key": "bad"}]},
            composition={
                "expression": f'{categories} if correct else ["bad"]',
                "inputs": [{"alias": "correct", "scorer_version_id": str(self.input_version.id)}],
            },
            created_by=None,
        )
        self.ingestion.upload(
            self.experiment.id,
            UploadSubmission(
                items=[self.item],
                results=[self.source_result, replace(self.request, scorer_version_id=version.id)],
            ),
        )
        result = OfflineEvaluationResult.objects.for_team(self.team.id).get(scorer_version=version)
        self.assertEqual(result.status, expected_status)
        self.assertEqual(result.error_code, "composite_formula_error" if expected_status == "error" else None)
        summary = (
            OfflineEvaluationReadService(team_id=self.team.id, user_access_control=None, can_read_scores=True)
            .list_summaries(self.experiment.id, OfflineReadQuery(scorer_version_ids=(version.id,)))
            .results[0]
        )
        self.assertTrue(all(category.count <= 1 for category in summary.categories))
        self.assertEqual(summary.status_counts.ok, int(expected_status == "ok"))

    def test_changed_input_conflicts_and_does_not_recompute(self) -> None:
        self.ingestion.upload(
            self.experiment.id, UploadSubmission(items=[self.item], results=[self.source_result, self.request])
        )
        with self.assertRaises(OfflineEvaluationConflict):
            self.ingestion.upload(
                self.experiment.id, UploadSubmission(results=[replace(self.source_result, value=False), self.request])
            )
        self.assertEqual(self.result().numeric_value, 1.0)

    def test_optional_composite_coverage_and_revoked_source_access(self) -> None:
        other_item = ItemSubmission(id=uuid4())
        self.ingestion.upload(
            self.experiment.id,
            UploadSubmission(
                items=[self.item, other_item],
                results=[self.source_result, self.request, replace(self.source_result, item_id=other_item.id)],
            ),
        )
        reads = OfflineEvaluationReadService(team_id=self.team.id, user_access_control=None, can_read_scores=True)
        summary = reads.list_summaries(
            self.experiment.id, OfflineReadQuery(scorer_version_ids=(self.version.id,))
        ).results[0]
        self.assertEqual(
            (summary.result_count, summary.missing_result_count, summary.not_requested_count, summary.mean),
            (1, 0, 1, 1.0),
        )
        denied_access = Mock()
        denied_access.filter_queryset_by_access_level.side_effect = lambda queryset, **kwargs: queryset.exclude(
            id=self.source.id
        )
        denied_reads = OfflineEvaluationReadService(
            team_id=self.team.id, user_access_control=denied_access, can_read_scores=True
        )
        self.assertEqual(denied_reads.list_summaries(self.experiment.id, OfflineReadQuery()).results, [])
        denied_ingestion = OfflineEvaluationIngestionService(
            team_id=self.team.id, user_access_control=denied_access, can_read_results=True
        )
        with self.assertRaises(OfflineEvaluationValidationError):
            denied_ingestion.upload(self.experiment.id, UploadSubmission(results=[self.request]))
        with self.assertRaises(OfflineEvaluationValidationError):
            denied_ingestion.upload(
                self.experiment.id, UploadSubmission(results=[replace(self.request, item_id=other_item.id)])
            )

    def test_bulk_upload_has_bounded_query_count(self) -> None:
        items = [ItemSubmission(id=uuid4()) for _ in range(250)]
        results = [
            result
            for item in items
            for result in (replace(self.request, item_id=item.id), replace(self.source_result, item_id=item.id))
        ]
        with (
            self.assertNumQueries(13),
            patch("products.ai_observability.backend.offline_evaluation_service.is_team_limited", return_value=False),
        ):
            self.ingestion.upload(self.experiment.id, UploadSubmission(items=items, results=results))
        self.assertEqual(OfflineEvaluationResult.objects.for_team(self.team.id).count(), 500)
