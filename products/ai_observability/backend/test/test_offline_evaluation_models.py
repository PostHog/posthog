from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import RestrictedError
from django.test import TestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.scoping import team_scope, unscoped
from posthog.models.scoping.manager import TeamScopeError

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

if TYPE_CHECKING:
    from posthog.models.scoping.root_mixin import TeamScopedRootMixin


class TestOfflineEvaluationModels(TestCase):
    organization: Organization
    team: Team
    experiment: OfflineExperiment
    item: OfflineExperimentItem
    scorer: ScoreDefinition
    scorer_version: ScoreDefinitionVersion
    result: OfflineEvaluationResult

    @classmethod
    def setUpTestData(cls) -> None:
        cls.organization, _, cls.team = Organization.objects.bootstrap(None)
        now = timezone.now()
        cls.experiment = OfflineExperiment.objects.for_team(cls.team.id).create(
            id=uuid4(),
            team=cls.team,
            name="Candidate model",
            started_at=now,
            created_at=now,
            submission_fingerprint="a" * 64,
        )
        cls.item = OfflineExperimentItem.objects.for_team(cls.team.id).create(
            id=uuid4(),
            team=cls.team,
            experiment=cls.experiment,
            accepted_at=now,
            payload_state=PayloadState.AVAILABLE,
            payload_expires_at=now + timedelta(days=30),
            submission_fingerprint="b" * 64,
        )
        cls.scorer = ScoreDefinition.objects.create(team=cls.team, name="Quality", kind="numeric")
        cls.scorer_version = cls.scorer.create_new_version(config={"min": 0, "max": 1}, created_by=None)
        cls.result = OfflineEvaluationResult.objects.for_team(cls.team.id).create(
            team=cls.team,
            item=cls.item,
            scorer_definition=cls.scorer,
            scorer_version=cls.scorer_version,
            status=OfflineEvaluationResult.Status.OK,
            numeric_value=0.8,
            accepted_at=now,
            payload_state=PayloadState.AVAILABLE,
            payload_expires_at=now + timedelta(days=30),
            submission_fingerprint="c" * 64,
        )
        OfflineExperimentItemPayload.objects.for_team(cls.team.id).create(
            team=cls.team,
            item=cls.item,
            data={"input": "A question", "output": "An answer", "expected_output": None},
        )
        OfflineEvaluationResultPayload.objects.for_team(cls.team.id).create(
            team=cls.team, result=cls.result, data={"reasoning": "The answer addresses the question."}
        )

    @parameterized.expand(
        [
            ("numeric", "ok", 0.0, None, None),
            ("small_numeric", "ok", 1e-7, None, None),
            ("large_numeric", "ok", 1e12, None, None),
            ("boolean", "ok", None, False, None),
            ("categorical", "ok", None, None, ["good", "clear"]),
            ("error", "error", None, None, None),
            ("skipped", "skipped", None, None, None),
            ("not_applicable", "not_applicable", None, None, None),
        ]
    )
    def test_accepts_typed_scores_and_non_score_outcomes(
        self,
        _name: str,
        status: str,
        numeric: float | None,
        boolean: bool | None,
        categorical: list[str] | None,
    ) -> None:
        OfflineEvaluationResult.objects.for_team(self.team.id).filter(pk=self.result.pk).update(
            status=status, numeric_value=numeric, boolean_value=boolean, categorical_values=categorical
        )
        self.result.refresh_from_db()
        self.assertEqual(
            (self.result.status, self.result.numeric_value, self.result.boolean_value, self.result.categorical_values),
            (status, numeric, boolean, categorical),
        )

    @parameterized.expand(
        [
            ("ok_without_value", {"numeric_value": None}),
            ("multiple_values", {"boolean_value": True}),
            ("error_with_value", {"status": "error"}),
            ("skipped_with_value", {"status": "skipped"}),
            ("not_applicable_with_value", {"status": "not_applicable"}),
            ("unknown_status", {"status": "pending"}),
            ("empty_categories", {"numeric_value": None, "categorical_values": []}),
            ("nan", {"numeric_value": float("nan")}),
            ("positive_infinity", {"numeric_value": float("inf")}),
            ("negative_infinity", {"numeric_value": float("-inf")}),
            ("error_code_on_success", {"error_code": "evaluator_failed"}),
            ("invalid_fingerprint", {"submission_fingerprint": "not-a-fingerprint"}),
        ]
    )
    def test_rejects_invalid_result_shapes(self, _name: str, changes: dict[str, object]) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            OfflineEvaluationResult.objects.for_team(self.team.id).filter(pk=self.result.pk).update(**changes)

    @parameterized.expand(
        [
            ("uploading_with_finish", {"status": "uploading", "finished_at": True}),
            ("completed_without_finish", {"status": "completed"}),
            ("failed_without_finish", {"status": "failed"}),
            ("unknown_status", {"status": "cancelled"}),
            ("finish_before_acceptance", {"status": "completed", "finished_at": False}),
            ("unknown_run_source", {"run_source": "browser"}),
        ]
    )
    def test_rejects_inconsistent_experiment_state(self, _name: str, changes: dict[str, object]) -> None:
        if "finished_at" in changes:
            changes = {
                **changes,
                "finished_at": self.experiment.created_at + timedelta(seconds=1 if changes["finished_at"] else -1),
            }
        with self.assertRaises(IntegrityError), transaction.atomic():
            OfflineExperiment.objects.for_team(self.team.id).filter(pk=self.experiment.pk).update(**changes)

    @parameterized.expand([("completed",), ("failed",)])
    def test_accepts_terminal_experiment_state(self, status: str) -> None:
        finished_at = self.experiment.created_at + timedelta(seconds=1)
        OfflineExperiment.objects.for_team(self.team.id).filter(pk=self.experiment.pk).update(
            status=status, finished_at=finished_at
        )
        self.experiment.refresh_from_db()
        self.assertEqual((self.experiment.status, self.experiment.finished_at), (status, finished_at))

    @parameterized.expand([("item",), ("result",)])
    def test_payload_expiry_must_follow_acceptance(self, owner_name: str) -> None:
        owner = self.item if owner_name == "item" else self.result
        with self.assertRaises(IntegrityError), transaction.atomic():
            type(owner).objects.for_team(self.team.id).filter(pk=owner.pk).update(payload_expires_at=owner.accepted_at)

    @parameterized.expand([("item",), ("result",)])
    def test_payload_must_be_a_json_object(self, owner_name: str) -> None:
        model = OfflineExperimentItemPayload if owner_name == "item" else OfflineEvaluationResultPayload
        with self.assertRaises(IntegrityError), transaction.atomic():
            model.objects.for_team(self.team.id).update(data=["not", "an", "object"])

    def test_one_result_per_item_and_scorer_version(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            OfflineEvaluationResult.objects.for_team(self.team.id).create(
                team=self.team,
                item=self.item,
                scorer_definition=self.scorer,
                scorer_version=self.scorer_version,
                status="ok",
                numeric_value=0.9,
                submission_fingerprint="d" * 64,
            )
        next_version = self.scorer.create_new_version(config={"min": 0, "max": 5}, created_by=None)
        new_result = OfflineEvaluationResult.objects.for_team(self.team.id).create(
            team=self.team,
            item=self.item,
            scorer_definition=self.scorer,
            scorer_version=next_version,
            status="ok",
            numeric_value=4,
            submission_fingerprint="d" * 64,
        )
        connection.check_constraints([OfflineEvaluationResult._meta.db_table])
        self.assertNotEqual(new_result.pk, self.result.pk)
        self.assertEqual(OfflineEvaluationResult.objects.for_team(self.team.id).filter(item=self.item).count(), 2)

    @parameterized.expand([("experiment",), ("item",)])
    def test_client_ids_are_required(self, model_name: str) -> None:
        instance: OfflineExperiment | OfflineExperimentItem
        if model_name == "experiment":
            instance = OfflineExperiment(
                team=self.team,
                name="Missing client ID",
                started_at=self.experiment.started_at,
                submission_fingerprint="d" * 64,
            )
        else:
            instance = OfflineExperimentItem(
                team=self.team, experiment=self.experiment, submission_fingerprint="d" * 64
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            instance.save(force_insert=True)

    @parameterized.expand(
        [
            ("experiment", OfflineExperiment),
            ("item", OfflineExperimentItem),
            ("result", OfflineEvaluationResult),
            ("item_payload", OfflineExperimentItemPayload),
            ("result_payload", OfflineEvaluationResultPayload),
        ]
    )
    def test_reads_fail_closed_and_stay_within_the_team(self, _name: str, model: type["TeamScopedRootMixin"]) -> None:
        _, _, other_team = Organization.objects.bootstrap(None)
        with unscoped(), self.assertRaises(TeamScopeError):
            model.objects.count()
        with team_scope(self.team.id):
            self.assertEqual(model.objects.count(), 1)
        self.assertEqual(model.objects.for_team(other_team.id).count(), 0)

    @parameterized.expand(
        [
            ("item", OfflineExperimentItem),
            ("result", OfflineEvaluationResult),
            ("item_payload", OfflineExperimentItemPayload),
            ("result_payload", OfflineEvaluationResultPayload),
        ]
    )
    def test_related_offline_rows_cannot_belong_to_different_teams(
        self, _name: str, model: type["TeamScopedRootMixin"]
    ) -> None:
        _, _, other_team = Organization.objects.bootstrap(None)
        values: dict[str, object] = {"team": other_team}
        if model is OfflineExperimentItem:
            values.update(id=uuid4(), experiment=self.experiment, submission_fingerprint="d" * 64)
        elif model is OfflineEvaluationResult:
            scorer = ScoreDefinition.objects.create(team=other_team, name="Quality", kind="numeric")
            version = scorer.create_new_version(config={"min": 0, "max": 5}, created_by=None)
            values.update(
                item=self.item,
                scorer_definition=scorer,
                scorer_version=version,
                status="ok",
                numeric_value=4,
                submission_fingerprint="d" * 64,
            )
        elif model is OfflineExperimentItemPayload:
            OfflineExperimentItemPayload.objects.for_team(self.team.id).filter(item=self.item).delete()
            values.update(item=self.item, data={"input": "Another question"})
        else:
            OfflineEvaluationResultPayload.objects.for_team(self.team.id).filter(result=self.result).delete()
            values.update(result=self.result, data={"reasoning": "An explanation"})

        with self.assertRaises(IntegrityError), transaction.atomic():
            model.objects.for_team(other_team.id).create(**values)
            connection.check_constraints([model._meta.db_table])

    @parameterized.expand(
        [
            ("foreign_scorer_bulk_create", False, "bulk_create"),
            ("foreign_scorer_update", False, "update"),
            ("wrong_definition_bulk_create", True, "bulk_create"),
            ("wrong_definition_update", True, "update"),
        ]
    )
    def test_results_require_a_scorer_version_from_their_team_and_definition(
        self, _name: str, same_team: bool, operation: str
    ) -> None:
        if same_team:
            scorer_team = self.team
        else:
            _, _, scorer_team = Organization.objects.bootstrap(None)
        scorer = ScoreDefinition.objects.create(team=scorer_team, name="Another quality scorer", kind="numeric")
        version = scorer.create_new_version(config={"min": 0, "max": 1}, created_by=None)
        definition = self.scorer if same_team else scorer

        with self.assertRaises(IntegrityError), transaction.atomic():
            if operation == "bulk_create":
                OfflineEvaluationResult.objects.for_team(self.team.id).bulk_create(
                    [
                        OfflineEvaluationResult(
                            team=self.team,
                            item=self.item,
                            scorer_definition=definition,
                            scorer_version=version,
                            status="ok",
                            numeric_value=0.5,
                            submission_fingerprint="d" * 64,
                        )
                    ]
                )
            else:
                OfflineEvaluationResult.objects.for_team(self.team.id).filter(pk=self.result.pk).update(
                    scorer_definition=definition, scorer_version=version
                )
            connection.check_constraints([OfflineEvaluationResult._meta.db_table])

    @parameterized.expand([("scorer_team",), ("version_definition",)])
    def test_referenced_scorer_ownership_cannot_be_reassigned(self, target: str) -> None:
        if target == "scorer_team":
            _, _, other_team = Organization.objects.bootstrap(None)
        else:
            other_scorer = ScoreDefinition.objects.create(team=self.team, name="Another quality scorer", kind="numeric")

        with self.assertRaises(IntegrityError), transaction.atomic():
            if target == "scorer_team":
                ScoreDefinition.objects.filter(pk=self.scorer.pk).update(team=other_team)
            else:
                ScoreDefinitionVersion.objects.filter(pk=self.scorer_version.pk).update(definition=other_scorer)
            connection.check_constraints([OfflineEvaluationResult._meta.db_table])

    @parameterized.expand(
        [
            ("revision_bulk_create", "revision", "bulk_create"),
            ("revision_update", "revision", "update"),
            ("item_version_bulk_create", "item_version", "bulk_create"),
            ("item_version_update", "item_version", "update"),
        ]
    )
    def test_dataset_references_cannot_belong_to_another_team(self, _name: str, target: str, operation: str) -> None:
        _, _, other_team = Organization.objects.bootstrap(None)
        dataset = Dataset.objects.for_team(other_team.id).create(team=other_team, name="Examples")
        revision = DatasetRevision.objects.for_team(other_team.id).create(team=other_team, dataset=dataset, revision=1)
        instance: OfflineExperiment | OfflineExperimentItem
        if target == "revision":
            instance = OfflineExperiment(
                id=uuid4(),
                team=self.team,
                name="Candidate model",
                started_at=self.experiment.started_at,
                dataset_revision=revision,
                submission_fingerprint="d" * 64,
            )
        else:
            dataset_item = DatasetItem.objects.for_team(other_team.id).create(team=other_team, dataset=dataset)
            item_version = DatasetItemVersion.objects.for_team(other_team.id).create(
                team=other_team,
                dataset=dataset,
                dataset_item=dataset_item,
                dataset_revision=revision,
                version=1,
                input={"question": "A question"},
            )
            instance = OfflineExperimentItem(
                id=uuid4(),
                team=self.team,
                experiment=self.experiment,
                dataset_item_version=item_version,
                submission_fingerprint="d" * 64,
            )

        with self.assertRaises(IntegrityError), transaction.atomic():
            if operation == "bulk_create":
                if isinstance(instance, OfflineExperiment):
                    OfflineExperiment.objects.for_team(self.team.id).bulk_create([instance])
                else:
                    OfflineExperimentItem.objects.for_team(self.team.id).bulk_create([instance])
            elif target == "revision":
                OfflineExperiment.objects.for_team(self.team.id).filter(pk=self.experiment.pk).update(
                    dataset_revision=revision
                )
            else:
                OfflineExperimentItem.objects.for_team(self.team.id).filter(pk=self.item.pk).update(
                    dataset_item_version=item_version
                )
            connection.check_constraints([instance._meta.db_table])

    def test_deleting_payloads_preserves_scores_and_item_identity(self) -> None:
        OfflineExperimentItemPayload.objects.for_team(self.team.id).filter(item=self.item).delete()
        OfflineEvaluationResultPayload.objects.for_team(self.team.id).filter(result=self.result).delete()

        self.item.refresh_from_db()
        self.result.refresh_from_db()
        self.assertEqual(self.item.experiment_id, self.experiment.pk)
        self.assertEqual(self.item.submission_fingerprint, "b" * 64)
        self.assertEqual(self.result.item_id, self.item.pk)
        self.assertEqual(self.result.scorer_version_id, self.scorer_version.pk)
        self.assertEqual(self.result.numeric_value, 0.8)
        self.assertEqual(self.result.submission_fingerprint, "c" * 64)

    def test_deleting_dataset_preserves_results_and_durable_provenance(self) -> None:
        dataset = Dataset.objects.for_team(self.team.id).create(team=self.team, name="Examples")
        revision = DatasetRevision.objects.for_team(self.team.id).create(team=self.team, dataset=dataset, revision=1)
        dataset_item = DatasetItem.objects.for_team(self.team.id).create(team=self.team, dataset=dataset)
        item_version = DatasetItemVersion.objects.for_team(self.team.id).create(
            team=self.team,
            dataset=dataset,
            dataset_item=dataset_item,
            dataset_revision=revision,
            version=1,
            input={"question": "A question"},
        )
        OfflineExperiment.objects.for_team(self.team.id).filter(pk=self.experiment.pk).update(
            dataset_revision=revision,
            dataset_identifier=str(dataset.pk),
            dataset_revision_identifier="1",
        )
        OfflineExperimentItem.objects.for_team(self.team.id).filter(pk=self.item.pk).update(
            dataset_item_version=item_version,
            dataset_item_identifier=str(dataset_item.pk),
            dataset_item_version_identifier="1",
        )
        connection.check_constraints()

        dataset_id = dataset.pk
        dataset.delete()
        connection.check_constraints()

        self.experiment.refresh_from_db()
        self.item.refresh_from_db()
        self.result.refresh_from_db()
        self.assertIsNone(self.experiment.dataset_revision_id)
        self.assertEqual(self.experiment.dataset_identifier, str(dataset_id))
        self.assertEqual(self.experiment.dataset_revision_identifier, "1")
        self.assertIsNone(self.item.dataset_item_version_id)
        self.assertEqual(self.item.dataset_item_identifier, str(dataset_item.pk))
        self.assertEqual(self.item.dataset_item_version_identifier, "1")
        self.assertEqual(self.result.scorer_version_id, self.scorer_version.pk)

    @parameterized.expand([("version",), ("scorer",)])
    def test_referenced_scorers_cannot_be_deleted(self, target: str) -> None:
        instance = self.scorer_version if target == "version" else self.scorer
        with self.assertRaises(RestrictedError):
            instance.delete()
        self.assertTrue(OfflineEvaluationResult.objects.for_team(self.team.id).filter(pk=self.result.pk).exists())

    @parameterized.expand([("experiment",), ("team",), ("project",), ("organization",)])
    def test_complete_deletion_cascades_through_offline_rows(self, target: str) -> None:
        parents = {
            "experiment": self.experiment,
            "team": self.team,
            "project": self.team.project,
            "organization": self.organization,
        }
        team_id = self.team.id
        parents[target].delete()

        for model in (
            OfflineExperiment,
            OfflineExperimentItem,
            OfflineEvaluationResult,
            OfflineExperimentItemPayload,
            OfflineEvaluationResultPayload,
        ):
            self.assertFalse(model.objects.for_team(team_id, canonical=True).exists())
        self.assertEqual(
            ScoreDefinitionVersion.objects.filter(pk=self.scorer_version.pk).exists(), target == "experiment"
        )
