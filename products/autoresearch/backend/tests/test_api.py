from typing import Any

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team

from products.actions.backend.models.action import Action
from products.autoresearch.backend.dataset.validation import ValidationResult, ValidationWarning
from products.autoresearch.backend.models import (
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchRun,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.presentation.views.serializers import (
    AutoresearchPipelineCreateSerializer,
    PopulationDefinitionField,
)
from products.autoresearch.backend.testing import TeamScopedTestMixin

MOCK_VALIDATION_OK = ValidationResult(
    can_proceed=True,
    requires_acknowledgement=False,
    estimated_training_rows=500,
    positive_count=100,
    negative_count=400,
    base_rate=0.2,
    inference_population_size=500,
    warnings=[],
)

MOCK_VALIDATION_ERROR = ValidationResult(
    can_proceed=False,
    requires_acknowledgement=False,
    estimated_training_rows=5,
    positive_count=5,
    negative_count=0,
    base_rate=1.0,
    inference_population_size=5,
    warnings=[
        ValidationWarning(code="low_volume", message="Only 5 users found.", severity="error"),
        ValidationWarning(code="low_positives", message="Only 5 positive examples.", severity="error"),
    ],
)


class TestAutoresearchPipelineAPI(TeamScopedTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/autoresearch"
        self._flag_patcher = patch(
            "products.autoresearch.backend.access.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self._flag_patcher.start()
        self.addCleanup(self._flag_patcher.stop)

    def _make_pipeline(self, **kwargs) -> AutoresearchPipeline:
        defaults = {
            "team": self.team,
            "created_by": self.user,
            "name": "Test Pipeline",
            "target_event": "$pageview",
            "horizon_days": 7,
            "iteration_budget": 50,
            "iteration_budget_remaining": 50,
        }
        defaults.update(kwargs)
        return AutoresearchPipeline.objects.create(**defaults)

    # ──────────────────────────────────────────── CRUD ────────────────────────────────────────────

    def test_create_pipeline(self):
        resp = self.client.post(
            f"{self.base_url}/",
            {"name": "My Pipeline", "target_event": "$signup", "horizon_days": 14},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["name"] == "My Pipeline"
        assert data["target_event"] == "$signup"
        assert data["status"] == "draft"
        # Auto-derived output property carries the horizon so same-target/different-horizon
        # pipelines don't $set the same person property.
        assert data["output_person_property"] == "predicted_p_signup_14d"
        assert AutoresearchPipeline.objects.filter(team=self.team, name="My Pipeline").exists()

    def test_create_pipeline_with_action_target(self):
        action = Action.objects.create(
            team=self.team, name="Interacted with file", steps_json=[{"event": "uploaded_file"}]
        )
        resp = self.client.post(
            f"{self.base_url}/",
            {
                "name": "Action Pipeline",
                "target_definition": {"type": "action", "action_id": action.id},
                "horizon_days": 14,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.json()
        data = resp.json()
        assert data["target_definition"] == {"type": "action", "action_id": action.id}
        # target_event is backfilled from the action name for display + property derivation.
        assert data["target_event"] == "Interacted with file"
        assert data["output_person_property"] == "predicted_p_interacted_with_file_14d"

    def test_create_pipeline_with_foreign_action_rejected(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        action = Action.objects.create(team=other_team, name="Foreign", steps_json=[{"event": "uploaded_file"}])
        resp = self.client.post(
            f"{self.base_url}/",
            {"name": "Bad", "target_definition": {"type": "action", "action_id": action.id}},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_pipeline_without_target_rejected(self):
        resp = self.client.post(f"{self.base_url}/", {"name": "No target"}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_list_pipelines_for_team(self):
        self._make_pipeline(name="Pipeline A")
        self._make_pipeline(name="Pipeline B")
        resp = self.client.get(f"{self.base_url}/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["count"] == 2

    def test_archived_pipelines_excluded_from_list(self):
        self._make_pipeline(name="Active")
        self._make_pipeline(name="Archived", status=AutoresearchPipeline.Status.ARCHIVED)
        resp = self.client.get(f"{self.base_url}/")
        assert resp.json()["count"] == 1
        assert resp.json()["results"][0]["name"] == "Active"

    def test_retrieve_pipeline(self):
        pipeline = self._make_pipeline()
        resp = self.client.get(f"{self.base_url}/{pipeline.id}/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["id"] == str(pipeline.id)

    def test_other_team_cannot_access_pipeline(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        pipeline = AutoresearchPipeline.objects.create(
            team=other_team,
            created_by=self.user,
            name="Other Team Pipeline",
            target_event="$click",
            iteration_budget=50,
            iteration_budget_remaining=50,
        )
        resp = self.client.get(f"/api/projects/{other_team.pk}/autoresearch/{pipeline.id}/")
        assert resp.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)

    # ──────────────────────────────────────── lifecycle actions ────────────────────────────────────

    # ─────────────────────────────────────── validate action ──────────────────────────────────────

    @patch(
        "products.autoresearch.backend.facade.api._validate_pipeline_definition",
        return_value=MOCK_VALIDATION_OK,
    )
    def test_validate_pipeline_success(self, _mock: MagicMock):
        resp = self.client.post(
            f"{self.base_url}/validate/",
            {"target_event": "$signup", "horizon_days": 7},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["can_proceed"] is True
        assert data["base_rate"] == pytest.approx(0.2)
        assert data["warnings"] == []

    @patch(
        "products.autoresearch.backend.facade.api._validate_pipeline_definition",
        return_value=MOCK_VALIDATION_ERROR,
    )
    def test_validate_pipeline_with_errors(self, _mock: MagicMock):
        resp = self.client.post(
            f"{self.base_url}/validate/",
            {"target_event": "$rare_event", "horizon_days": 7},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["can_proceed"] is False
        assert len(data["warnings"]) == 2
        assert data["warnings"][0]["severity"] == "error"

    def test_validate_missing_target_event_returns_400(self):
        resp = self.client.post(f"{self.base_url}/validate/", {}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # ──────────────────────────────────────── train action ────────────────────────────────────────

    # ──────────────────────────────────── update restrictions ─────────────────────────────────────

    def _make_trained_pipeline(self) -> AutoresearchPipeline:
        pipeline = self._make_pipeline()
        AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            model_recipe={"stub": True},
            recipe_hash="abc123",
        )
        return pipeline

    @parameterized.expand(
        [
            ("target_event", {"target_event": "other_event"}),
            ("horizon_days", {"horizon_days": 30}),
            ("training_lookback_days", {"training_lookback_days": 90}),
            ("training_population", {"training_population": {"kind": "ever_performed_event"}}),
            ("inference_population", {"inference_population": {"kind": "ever_performed_event"}}),
        ]
    )
    def test_model_defining_fields_frozen_after_training(self, field: str, payload: dict):
        pipeline = self._make_trained_pipeline()
        resp = self.client.patch(f"{self.base_url}/{pipeline.id}/", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        pipeline.refresh_from_db()
        assert getattr(pipeline, field) != payload[field]

    def test_metadata_editable_after_training(self):
        pipeline = self._make_trained_pipeline()
        resp = self.client.patch(
            f"{self.base_url}/{pipeline.id}/",
            {"name": "Renamed", "cadence_days": 3, "iteration_budget": 20},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.json()
        pipeline.refresh_from_db()
        assert pipeline.name == "Renamed"
        assert pipeline.cadence_days == 3

    def test_resubmitting_unchanged_target_after_training_is_allowed(self):
        pipeline = self._make_trained_pipeline()
        resp = self.client.patch(f"{self.base_url}/{pipeline.id}/", {"target_event": "$pageview"}, format="json")
        assert resp.status_code == status.HTTP_200_OK, resp.json()

    def test_target_editable_before_any_model_is_trained(self):
        pipeline = self._make_pipeline()
        resp = self.client.patch(f"{self.base_url}/{pipeline.id}/", {"horizon_days": 30}, format="json")
        assert resp.status_code == status.HTTP_200_OK, resp.json()
        pipeline.refresh_from_db()
        assert pipeline.horizon_days == 30

    # ─────────────────────────────── output_person_property guards ────────────────────────────────

    def test_output_person_property_collision_rejected(self):
        self._make_pipeline(name="First", output_person_property="predicted_p_signup_7d")
        resp = self.client.post(
            f"{self.base_url}/",
            {"name": "Second", "target_event": "other_event", "output_person_property": "predicted_p_signup_7d"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["attr"] == "output_person_property"

    def test_derived_output_person_property_collision_rejected(self):
        self._make_pipeline(name="First", output_person_property="predicted_p_signup_14d")
        # Same target + horizon derives the same property name.
        resp = self.client.post(
            f"{self.base_url}/",
            {"name": "Second", "target_event": "$signup", "horizon_days": 14},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_oversized_action_name_target_rejected(self):
        action = Action.objects.create(team=self.team, name="x" * 300, steps_json=[{"event": "uploaded_file"}])
        resp = self.client.post(
            f"{self.base_url}/",
            {"name": "Oversized", "target_definition": {"type": "action", "action_id": action.id}},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # ─────────────────────────────────── nested resources ─────────────────────────────────────────

    def test_list_models_for_pipeline(self):
        pipeline = self._make_pipeline()
        training_run = AutoresearchTrainingRun.objects.create(pipeline=pipeline, status="completed")
        AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            model_recipe={"stub": True},
            recipe_hash="abc123",
            holdout_score=0.7,
            source_training_run=training_run,
        )
        resp = self.client.get(f"{self.base_url}/{pipeline.id}/models/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["count"] == 1
        assert resp.json()["results"][0]["role"] == "champion"
        # The agent brief tells agents to look up a champion's bundle via source_training_run.
        assert resp.json()["results"][0]["source_training_run"] == str(training_run.id)

    def test_list_training_runs_for_pipeline(self):
        pipeline = self._make_pipeline()
        AutoresearchTrainingRun.objects.create(pipeline=pipeline, status="completed", iteration_count=1)
        resp = self.client.get(f"{self.base_url}/{pipeline.id}/training_runs/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["count"] == 1

    def test_list_runs_for_pipeline(self):
        pipeline = self._make_pipeline()
        model = AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            model_recipe={"stub": True},
            recipe_hash="def456",
            holdout_score=0.6,
        )
        AutoresearchRun.objects.create(pipeline=pipeline, model=model, status="completed", rows_scored=100)
        resp = self.client.get(f"{self.base_url}/{pipeline.id}/runs/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["count"] == 1

    def test_models_not_leaked_across_pipelines(self):
        pipeline_a = self._make_pipeline(name="Pipeline A")
        pipeline_b = self._make_pipeline(name="Pipeline B")
        AutoresearchModel.objects.create(
            pipeline=pipeline_a,
            role=AutoresearchModel.Role.CHAMPION,
            model_recipe={"stub": True},
            recipe_hash="aaa",
            holdout_score=0.7,
        )
        resp = self.client.get(f"{self.base_url}/{pipeline_b.id}/models/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["count"] == 0


class TestPipelineCreateSerializerValidation(SimpleTestCase):
    # Field- and target-shape validation runs in memory, so these cases never need a DB.
    # The endpoint wiring (bad body -> 400) is covered by the APIBaseTest create tests above.

    def _serializer(self, **overrides: Any) -> AutoresearchPipelineCreateSerializer:
        data: dict[str, Any] = {"name": "Pipeline", "target_event": "$pageview", **overrides}
        return AutoresearchPipelineCreateSerializer(data=data, context={"get_team": lambda: None})

    @parameterized.expand(
        [
            ("horizon_days_below_min", "horizon_days", 0),
            ("horizon_days_above_max", "horizon_days", 366),
            ("lookback_below_min", "training_lookback_days", 6),
            ("lookback_above_max", "training_lookback_days", 731),
            ("cadence_below_min", "cadence_days", 0),
            ("cadence_above_max", "cadence_days", 366),
            ("iteration_budget_below_min", "iteration_budget", 0),
            ("iteration_budget_above_max", "iteration_budget", 501),
        ]
    )
    def test_out_of_range_numeric_field_rejected(self, _name: str, field: str, value: int) -> None:
        serializer = self._serializer(**{field: value})
        assert not serializer.is_valid()
        assert field in serializer.errors

    @parameterized.expand(
        [
            ("not_an_object", ["properties"]),
            ("properties_not_a_list", {"properties": {"key": "email"}}),
            ("unknown_kind", {"kind": "bogus"}),
            ("missing_days", {"kind": "performed_event_within_days"}),
            ("days_not_int", {"kind": "person_first_seen_within_days", "days": "14"}),
            ("days_out_of_range", {"kind": "performed_event_within_days", "days": 100000}),
            ("missing_event_for_repeat", {"kind": "ever_performed_event"}),
        ]
    )
    def test_uncompilable_population_rejected(self, _name: str, population: Any) -> None:
        serializer = self._serializer(training_population=population)
        assert not serializer.is_valid()
        assert "training_population" in serializer.errors

    @parameterized.expand(
        [
            ("empty", {}),
            ("properties", {"properties": [{"key": "email", "type": "person", "operator": "is_set"}]}),
            ("kind_any_event", {"kind": "performed_event_within_days", "days": 30}),
            ("kind_with_event", {"kind": "ever_performed_event", "event": "checkout"}),
            ("kind_adoption", {"kind": "active_not_performed_target", "active_within_days": 30}),
            ("kind_repeat_target", {"kind": "ever_performed_target"}),
        ]
    )
    def test_compilable_population_accepted(self, _name: str, population: Any) -> None:
        # Field-level only: the full serializer's validate() needs the DB for the
        # output_person_property collision check, which SimpleTestCase forbids.
        assert PopulationDefinitionField().run_validation(population) == population

    @parameterized.expand(
        [
            ("newline", "signup\ncomplete"),
            ("backtick", "signup`whoami`"),
            ("template_braces", "signup {{instructions}}"),
            ("control_char", "signup\x07"),
        ]
    )
    def test_injection_shaped_target_event_rejected(self, _name: str, target_event: str) -> None:
        serializer = self._serializer(target_event=target_event)
        assert not serializer.is_valid()
        assert "target_event" in serializer.errors

    @parameterized.expand(
        [
            ("event_with_filters", {"type": "event", "filters": [{"key": "$current_url"}]}),
            ("legacy_event_shape", {"event": "$pageview", "filters": []}),
            ("unknown_type", {"type": "cohort", "cohort_id": 1}),
        ]
    )
    def test_unsupported_event_target_definition_rejected(self, _name: str, definition: dict) -> None:
        serializer = self._serializer(target_definition=definition)
        assert not serializer.is_valid()
        assert "target_definition" in serializer.errors

    @parameterized.expand(
        [
            ("space", "predicted p"),
            ("backtick", "predicted`p"),
            ("braces", "predicted{p}"),
            ("newline", "predicted\np"),
        ]
    )
    def test_invalid_output_person_property_shape_rejected(self, _name: str, value: str) -> None:
        serializer = self._serializer(output_person_property=value)
        assert not serializer.is_valid()
        assert "output_person_property" in serializer.errors
