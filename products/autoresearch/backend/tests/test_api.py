import uuid
import base64
from typing import Any

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team
from posthog.storage.object_storage import ObjectStorageError

from products.actions.backend.models.action import Action
from products.autoresearch.backend.dataset.templates import TEMPLATES
from products.autoresearch.backend.dataset.validation import ValidationResult, ValidationWarning
from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchRun,
    AutoresearchSuggestion,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.presentation.views.serializers import (
    _POPULATION_KIND_REQUIRED_DAYS,
    POPULATION_KINDS,
    VALIDATION_WARNING_CODES,
    AutoresearchPipelineCreateSerializer,
    PopulationDefinitionField,
    ValidationWarningSerializer,
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

    def test_create_pipeline_with_deleted_action_rejected(self):
        action = Action.objects.create(
            team=self.team, name="Gone", steps_json=[{"event": "uploaded_file"}], deleted=True
        )
        resp = self.client.post(
            f"{self.base_url}/",
            {"name": "Bad", "target_definition": {"type": "action", "action_id": action.id}},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["attr"] == "target_definition"

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
        assert resp.json()["target_definition"] == {"type": "event"}

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
        assert _mock.call_args.kwargs["user"] == self.user

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

    @parameterized.expand(
        [
            ("missing_target", {}),
            ("list_shaped_target_definition", {"target_event": "$signup", "target_definition": [1]}),
        ]
    )
    def test_validate_rejects(self, _name: str, body: dict):
        resp = self.client.post(f"{self.base_url}/validate/", body, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand(
        [
            ("omitted", {}, {"kind": "ever_performed_target"}),
            ("empty", {"inference_population": {}}, {"kind": "ever_performed_target"}),
            ("given", {"inference_population": {"kind": "person_first_seen_within_days", "days": 14}}, None),
        ]
    )
    @patch(
        "products.autoresearch.backend.facade.api._validate_pipeline_definition",
        return_value=MOCK_VALIDATION_OK,
    )
    def test_validate_previews_the_population_creation_would_store(
        self, _name: str, extra: dict, expected: dict | None, _mock: MagicMock
    ):
        body = {"target_event": "$signup", "training_population": {"kind": "ever_performed_target"}, **extra}
        resp = self.client.post(f"{self.base_url}/validate/", body, format="json")
        assert resp.status_code == status.HTTP_200_OK
        expected = expected if expected is not None else extra["inference_population"]
        assert _mock.call_args.kwargs["inference_population"] == expected

    @parameterized.expand(
        [
            ("validate", "validate", {"target_event": "$signup"}),
            ("resolve_template", "resolve-template", {"template_key": "likely_active_soon"}),
        ]
    )
    @patch(
        "products.autoresearch.backend.dataset.templates.resolve_activity_event",
        return_value=("$pageview", []),
    )
    @patch(
        "products.autoresearch.backend.facade.api._validate_pipeline_definition",
        return_value=MOCK_VALIDATION_OK,
    )
    def test_query_backed_helpers_need_the_query_scope(
        self, _name: str, path: str, body: dict, _validate: MagicMock, _resolve: MagicMock
    ):
        self.client.logout()
        read_only = self.create_personal_api_key_with_scopes(["autoresearch:read"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {read_only}")
        assert (
            self.client.post(f"{self.base_url}/{path}/", body, format="json").status_code == status.HTTP_403_FORBIDDEN
        )
        with_query = self.create_personal_api_key_with_scopes(["autoresearch:read", "query:read"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {with_query}")
        assert self.client.post(f"{self.base_url}/{path}/", body, format="json").status_code == status.HTTP_200_OK

    @parameterized.expand(
        [
            ("validate", "validate/", ["autoresearch:read", "query:read"], status.HTTP_200_OK),
            ("create", "", ["autoresearch:write"], status.HTTP_201_CREATED),
        ]
    )
    @patch(
        "products.autoresearch.backend.facade.api._validate_pipeline_definition",
        return_value=MOCK_VALIDATION_OK,
    )
    def test_action_targets_need_the_action_scope(
        self, _name: str, path: str, scopes: list[str], ok_status: int, _mock: MagicMock
    ):
        action = Action.objects.create(
            team=self.team, name="Interacted with file", steps_json=[{"event": "uploaded_file"}]
        )
        body = {"name": "Action Pipeline", "target_definition": {"type": "action", "action_id": action.id}}
        self.client.logout()
        without = self.create_personal_api_key_with_scopes(scopes)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {without}")
        resp = self.client.post(f"{self.base_url}/{path}", body, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["attr"] == "target_definition"
        with_action = self.create_personal_api_key_with_scopes([*scopes, "action:read"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {with_action}")
        assert self.client.post(f"{self.base_url}/{path}", body, format="json").status_code == ok_status

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

    @parameterized.expand([("archived",), ("unknown",)])
    def test_update_of_missing_pipeline_returns_404(self, case: str):
        if case == "archived":
            pipeline_id = self._make_pipeline(status=AutoresearchPipeline.Status.ARCHIVED).id
        else:
            pipeline_id = uuid.uuid4()
        resp = self.client.patch(f"{self.base_url}/{pipeline_id}/", {"name": "Renamed"}, format="json")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

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
        run = AutoresearchTrainingRun.objects.create(pipeline=pipeline, status="completed", iteration_count=1)
        AutoresearchIteration.objects.create(
            pipeline=pipeline,
            training_run=run,
            iteration_number=0,
            recipe_hash="abc",
            recipe_snapshot={"feature_sql": "SELECT 1"},
            model_spec={"model_class": "m"},
            status="kept",
        )
        resp = self.client.get(f"{self.base_url}/{pipeline.id}/training_runs/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["count"] == 1
        # The list carries the trail without recipes; history is where a recipe is read back.
        trail_entry = resp.json()["results"][0]["iterations"][0]
        assert trail_entry["model_spec"] == {"model_class": "m"}
        assert "recipe_snapshot" not in trail_entry

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

    @parameterized.expand(["models", "runs", "training_runs"])
    def test_nested_retrieve_is_scoped_to_the_parent_pipeline(self, resource: str):
        pipeline_a = self._make_pipeline(name="Pipeline A")
        pipeline_b = self._make_pipeline(name="Pipeline B")
        training_run = AutoresearchTrainingRun.objects.create(pipeline=pipeline_a, status="completed")
        model = AutoresearchModel.objects.create(
            pipeline=pipeline_a,
            role=AutoresearchModel.Role.CHAMPION,
            model_recipe={"stub": True},
            recipe_hash="aaa",
            holdout_score=0.7,
            source_training_run=training_run,
        )
        run = AutoresearchRun.objects.create(pipeline=pipeline_a, model=model, status="completed", rows_scored=1)
        row_id = {"models": model.id, "runs": run.id, "training_runs": training_run.id}[resource]

        resp = self.client.get(f"{self.base_url}/{pipeline_b.id}/{resource}/{row_id}/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        resp = self.client.get(f"{self.base_url}/{pipeline_a.id}/{resource}/not-a-uuid/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        resp = self.client.get(f"{self.base_url}/{pipeline_a.id}/{resource}/{row_id}/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["id"] == str(row_id)

    # ──────────────────────────────────────────── templates ────────────────────────────────────────────

    def test_list_templates_returns_every_template(self):
        resp = self.client.get(f"{self.base_url}/templates/")
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert {t["key"] for t in data} == set(TEMPLATES)
        for field in (
            "key",
            "display_name",
            "description",
            "default_horizon_days",
            "requires_user_event",
            "requires_activity_resolution",
            "notes",
        ):
            assert field in data[0]

    @patch(
        "products.autoresearch.backend.dataset.templates.resolve_activity_event",
        return_value=("$pageview", ["$screen"]),
    )
    def test_resolve_template_runs_as_the_request_user(self, resolve_activity: MagicMock):
        resp = self.client.post(
            f"{self.base_url}/resolve-template/",
            {"template_key": "likely_active_soon"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["target_event"] == "$pageview"
        assert data["horizon_days"] == 7
        assert data["activity_event_alternatives"] == ["$screen"]
        assert data["training_lookback_days"] == 180
        for field in ("training_population", "inference_population", "output_person_property", "suggested_name"):
            assert field in data
        assert resolve_activity.call_args.kwargs["user"] == self.user

    @patch(
        "products.autoresearch.backend.dataset.templates.resolve_activity_event",
        return_value=("$pageview", []),
    )
    def test_resolve_template_horizon_override(self, _mock: MagicMock):
        resp = self.client.post(
            f"{self.base_url}/resolve-template/",
            {"template_key": "likely_active_soon", "horizon_days": 30},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["horizon_days"] == 30

    def test_resolve_template_feature_adoption_uses_the_supplied_event(self):
        resp = self.client.post(
            f"{self.base_url}/resolve-template/",
            {"template_key": "feature_adoption", "target_event": "feature_clicked"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["target_event"] == "feature_clicked"

    @parameterized.expand(
        [
            ("missing_required_target_event", {"template_key": "feature_adoption"}),
            ("unknown_template_key", {"template_key": "not_a_real_template"}),
            ("own_prediction_event", {"template_key": "feature_adoption", "target_event": "autoresearch_prediction"}),
            ("unsafe_target_event", {"template_key": "repeat_key_behavior", "target_event": "signup`whoami`"}),
        ]
    )
    def test_resolve_template_rejects(self, _name: str, body: dict):
        resp = self.client.post(f"{self.base_url}/resolve-template/", body, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


class TestValidationWarningSerializer(SimpleTestCase):
    def test_help_text_names_every_code_the_validator_emits(self) -> None:
        help_text = str(ValidationWarningSerializer().fields["code"].help_text)
        assert all(f"'{code}'" in help_text for code in VALIDATION_WARNING_CODES)


class TestAutoresearchSuggestionAPI(TeamScopedTestMixin, APIBaseTest):
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

    def _suggestions_url(self, pipeline_id: object) -> str:
        return f"{self.base_url}/{pipeline_id}/suggestions/"

    # ──────────────────────────────────────────── create ──────────────────────────────────────────

    def test_create_suggestion(self):
        pipeline = self._make_pipeline()
        resp = self.client.post(
            self._suggestions_url(pipeline.id),
            {"prompt": "try a gradient boosting model", "priority": "consider"},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["prompt"] == "try a gradient boosting model"
        assert data["priority"] == "consider"
        assert data["status"] == "queued"
        assert data["source"] == "user"
        assert AutoresearchSuggestion.objects.filter(pipeline=pipeline).count() == 1

    def test_create_suggestion_try_next_priority(self):
        pipeline = self._make_pipeline()
        resp = self.client.post(
            self._suggestions_url(pipeline.id),
            {"prompt": "remove recency features", "priority": "try_next"},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()["priority"] == "try_next"

    def test_create_suggestion_default_priority_is_consider(self):
        pipeline = self._make_pipeline()
        resp = self.client.post(
            self._suggestions_url(pipeline.id),
            {"prompt": "try a different model"},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()["priority"] == "consider"

    def test_create_suggestion_archived_pipeline_returns_400(self):
        pipeline = self._make_pipeline(status=AutoresearchPipeline.Status.ARCHIVED)
        # Archived pipelines are excluded from the queryset; suggestions endpoint
        # does its own lookup and returns 400 (not 404) so the error is clear.
        resp = self.client.post(
            self._suggestions_url(pipeline.id),
            {"prompt": "try XGBoost"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_suggestion_on_a_missing_pipeline_returns_404(self):
        resp = self.client.post(self._suggestions_url(uuid.uuid4()), {"prompt": "try XGBoost"}, format="json")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_create_suggestion_missing_prompt_returns_400(self):
        pipeline = self._make_pipeline()
        resp = self.client.post(self._suggestions_url(pipeline.id), {}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # ──────────────────────────────────────────── list ────────────────────────────────────────────

    def test_list_suggestions(self):
        pipeline = self._make_pipeline()
        AutoresearchSuggestion.objects.create(
            pipeline=pipeline,
            created_by=self.user,
            prompt="first suggestion",
            priority=AutoresearchSuggestion.Priority.CONSIDER,
            source=AutoresearchSuggestion.Source.USER,
        )
        AutoresearchSuggestion.objects.create(
            pipeline=pipeline,
            created_by=self.user,
            prompt="second suggestion",
            priority=AutoresearchSuggestion.Priority.TRY_NEXT,
            source=AutoresearchSuggestion.Source.USER,
        )
        resp = self.client.get(self._suggestions_url(pipeline.id))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["count"] == 2

    def test_suggestions_not_leaked_across_pipelines(self):
        pipeline_a = self._make_pipeline(name="Pipeline A")
        pipeline_b = self._make_pipeline(name="Pipeline B")
        AutoresearchSuggestion.objects.create(
            pipeline=pipeline_a,
            created_by=self.user,
            prompt="only for A",
            source=AutoresearchSuggestion.Source.USER,
        )
        resp = self.client.get(self._suggestions_url(pipeline_b.id))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["count"] == 0

    # ──────────────────────────────────────────── retrieve ────────────────────────────────────────

    def test_retrieve_suggestion(self):
        pipeline = self._make_pipeline()
        suggestion = AutoresearchSuggestion.objects.create(
            pipeline=pipeline,
            created_by=self.user,
            prompt="use day-of-week features",
            priority=AutoresearchSuggestion.Priority.TRY_NEXT,
            status=AutoresearchSuggestion.Status.QUEUED,
            source=AutoresearchSuggestion.Source.USER,
        )
        resp = self.client.get(f"{self._suggestions_url(pipeline.id)}{suggestion.id}/")
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["id"] == str(suggestion.id)
        assert data["prompt"] == "use day-of-week features"
        assert data["status"] == "queued"

    def test_retrieve_suggestion_wrong_pipeline_returns_404(self):
        pipeline_a = self._make_pipeline(name="Pipeline A")
        pipeline_b = self._make_pipeline(name="Pipeline B")
        suggestion = AutoresearchSuggestion.objects.create(
            pipeline=pipeline_a,
            created_by=self.user,
            prompt="belongs to A",
            source=AutoresearchSuggestion.Source.USER,
        )
        resp = self.client.get(f"{self._suggestions_url(pipeline_b.id)}{suggestion.id}/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    # ──────────────────────────────────────────── respond ─────────────────────────────────────────

    def _make_suggestion(self, pipeline: AutoresearchPipeline, status_value: str = "queued") -> AutoresearchSuggestion:
        return AutoresearchSuggestion.objects.create(
            pipeline=pipeline,
            created_by=self.user,
            prompt="try a calibrated logistic regression",
            priority=AutoresearchSuggestion.Priority.TRY_NEXT,
            source=AutoresearchSuggestion.Source.USER,
            status=status_value,
        )

    def _link_iteration(self, suggestion: AutoresearchSuggestion) -> AutoresearchIteration:
        run = AutoresearchTrainingRun.objects.create(pipeline=suggestion.pipeline, status="running")
        return AutoresearchIteration.objects.create(
            pipeline=suggestion.pipeline,
            training_run=run,
            parent_suggestion=suggestion,
            iteration_number=0,
            recipe_hash="abc",
            recipe_snapshot={"feature_sql": "SELECT 1"},
            model_spec={"model_class": "m"},
            status="kept",
        )

    def _respond(self, suggestion: AutoresearchSuggestion, body: dict):
        return self.client.post(
            f"{self._suggestions_url(suggestion.pipeline_id)}{suggestion.id}/respond/", body, format="json"
        )

    def test_respond_sets_status_and_agent_response(self):
        pipeline = self._make_pipeline()
        suggestion = self._make_suggestion(pipeline)
        iteration = self._link_iteration(suggestion)
        resp = self._respond(
            suggestion, {"status": "acted_on", "agent_response": "Spawned iter 2 with LR + calibration."}
        )
        assert resp.status_code == status.HTTP_200_OK, resp.json()
        data = resp.json()
        assert data["status"] == "acted_on"
        assert data["agent_response"] == "Spawned iter 2 with LR + calibration."
        assert data["linked_iteration_ids"] == [str(iteration.id)]
        suggestion.refresh_from_db()
        assert suggestion.status == "acted_on"

    def test_respond_acted_on_needs_a_linked_iteration(self):
        suggestion = self._make_suggestion(self._make_pipeline())
        resp = self._respond(suggestion, {"status": "acted_on", "agent_response": "done"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "parent_suggestion" in str(resp.json())

    @parameterized.expand(
        [
            ("acted_on_back_to_picked_up", "acted_on", "picked_up"),
            ("acted_on_to_dismissed", "acted_on", "dismissed"),
            ("dismissed_back_to_picked_up", "dismissed", "picked_up"),
        ]
    )
    def test_respond_refuses_a_backward_transition(self, _name: str, current: str, requested: str):
        suggestion = self._make_suggestion(self._make_pipeline(), status_value=current)
        resp = self._respond(suggestion, {"status": requested, "agent_response": "changed my mind"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        suggestion.refresh_from_db()
        assert suggestion.status == current

    def test_respond_same_status_updates_the_note_and_blank_clears_it(self):
        suggestion = self._make_suggestion(self._make_pipeline())
        assert self._respond(suggestion, {"status": "picked_up", "agent_response": "first"}).status_code == 200
        resp = self._respond(suggestion, {"status": "picked_up"})
        assert resp.json()["agent_response"] == "first"
        resp = self._respond(suggestion, {"status": "picked_up", "agent_response": ""})
        assert resp.json()["agent_response"] == ""

    def test_respond_dismissed_without_a_reason_returns_400(self):
        suggestion = self._make_suggestion(self._make_pipeline())
        resp = self._respond(suggestion, {"status": "dismissed"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "agent_response" in str(resp.json())
        # A reason recorded earlier satisfies a repeated dismissal that omits the note.
        assert self._respond(suggestion, {"status": "dismissed", "agent_response": "dead end"}).status_code == 200
        resp = self._respond(suggestion, {"status": "dismissed"})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["agent_response"] == "dead end"

    def test_respond_after_pipeline_archived_returns_400(self):
        pipeline = self._make_pipeline()
        suggestion = self._make_suggestion(pipeline)
        pipeline.status = AutoresearchPipeline.Status.ARCHIVED
        pipeline.save(update_fields=["status"])
        resp = self._respond(suggestion, {"status": "picked_up"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "archived" in str(resp.json())

    @parameterized.expand([("retrieve",), ("respond",)])
    def test_non_uuid_suggestion_id_returns_404(self, action: str):
        pipeline = self._make_pipeline()
        url = f"{self._suggestions_url(pipeline.id)}not-a-uuid/"
        if action == "retrieve":
            resp = self.client.get(url)
        else:
            resp = self.client.post(f"{url}respond/", {"status": "picked_up"}, format="json")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_list_reads_linked_iterations_in_one_query(self):
        pipeline = self._make_pipeline()
        for _ in range(3):
            self._link_iteration(self._make_suggestion(pipeline))
        with CaptureQueriesContext(connection) as queries:
            resp = self.client.get(self._suggestions_url(pipeline.id))
        assert resp.status_code == status.HTTP_200_OK
        assert all(len(row["linked_iteration_ids"]) == 1 for row in resp.json()["results"])
        assert sum("autoresearchiteration" in q["sql"].lower() for q in queries.captured_queries) == 1

    def test_agent_authored_suggestion_has_no_creator(self):
        pipeline = self._make_pipeline()
        suggestion = AutoresearchSuggestion.objects.create(
            pipeline=pipeline, prompt="from the agent", source=AutoresearchSuggestion.Source.AGENT
        )
        resp = self.client.get(f"{self._suggestions_url(pipeline.id)}{suggestion.id}/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["created_by"] is None

    def test_respond_dismissed(self):
        pipeline = self._make_pipeline()
        suggestion = self._make_suggestion(pipeline)
        resp = self.client.post(
            f"{self._suggestions_url(pipeline.id)}{suggestion.id}/respond/",
            {"status": "dismissed", "agent_response": "Already a dead-end in a prior run."},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["status"] == "dismissed"

    def test_respond_invalid_status_returns_400(self):
        pipeline = self._make_pipeline()
        suggestion = self._make_suggestion(pipeline)
        resp = self.client.post(
            f"{self._suggestions_url(pipeline.id)}{suggestion.id}/respond/",
            {"status": "queued"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_respond_wrong_pipeline_returns_404(self):
        pipeline_a = self._make_pipeline(name="Pipeline A")
        pipeline_b = self._make_pipeline(name="Pipeline B")
        suggestion = self._make_suggestion(pipeline_a)
        resp = self.client.post(
            f"{self._suggestions_url(pipeline_b.id)}{suggestion.id}/respond/",
            {"status": "acted_on"},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND


class _InMemoryStorage:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def write(self, key, content, extras=None, bucket=None) -> None:
        self.store[key] = content if isinstance(content, bytes) else content.encode("utf-8")

    def read_bytes(self, key, bucket=None, *, missing_ok: bool = False):
        if key in self.store:
            return self.store[key]
        if missing_ok:
            return None
        raise FileNotFoundError(key)

    def delete(self, key, bucket=None) -> None:
        self.store.pop(key, None)

    def list_objects(self, prefix):
        keys = [k for k in self.store if k.startswith(prefix)]
        return keys or None


class TestAutoresearchArtifactAPI(TeamScopedTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/autoresearch"
        self._flag_patcher = patch(
            "products.autoresearch.backend.access.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self._flag_patcher.start()
        self.addCleanup(self._flag_patcher.stop)

        self._storage_patcher = patch(
            "products.autoresearch.backend.training.artifacts.object_storage",
            _InMemoryStorage(),
        )
        self._storage_patcher.start()
        self.addCleanup(self._storage_patcher.stop)

        self.pipeline = AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="Artifacts Pipeline",
            target_event="$pageview",
            horizon_days=7,
        )
        self.training_run = AutoresearchTrainingRun.objects.create(
            pipeline=self.pipeline, status="running", iteration_count=0
        )

    def _artifacts_url(self, suffix: str = "") -> str:
        return f"{self.base_url}/{self.pipeline.id}/training_runs/{self.training_run.id}/artifacts{suffix}"

    def _upload(self, path: str, body: bytes):
        return self.client.post(
            self._artifacts_url("/upload"),
            {"path": path, "content_base64": base64.b64encode(body).decode("ascii")},
            format="json",
        )

    def test_upload_then_get_roundtrip(self):
        with CaptureQueriesContext(connection) as queries:
            resp = self._upload("train.py", b"print('train')")
        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        # The write happens under the run row lock completion takes, so it cannot land on a frozen bundle.
        assert any("FOR UPDATE" in q["sql"] for q in queries.captured_queries)
        assert resp.json()["path"] == "train.py"
        assert resp.json()["size_bytes"] == 14

        resp = self.client.post(self._artifacts_url("/get"), {"path": "train.py"}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert base64.b64decode(resp.json()["content_base64"]) == b"print('train')"

    def test_list_artifacts(self):
        self._upload("train.py", b"a")
        self._upload("predict.py", b"b")
        resp = self.client.get(self._artifacts_url())
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["count"] == 2
        assert sorted(data["paths"]) == ["predict.py", "train.py"]

    def test_delete_artifact(self):
        self._upload("train.py", b"a")
        resp = self.client.post(self._artifacts_url("/delete"), {"path": "train.py"}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["deleted"] is True
        resp = self.client.post(self._artifacts_url("/delete"), {"path": "train.py"}, format="json")
        assert resp.json()["deleted"] is False

    def test_bundle_frozen_once_run_is_no_longer_running(self):
        self._upload("train.py", b"print('train')")
        self.training_run.status = AutoresearchTrainingRun.Status.COMPLETED
        self.training_run.save(update_fields=["status"])

        resp = self._upload("predict.py", b"print('predict')")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

        resp = self.client.post(self._artifacts_url("/delete"), {"path": "train.py"}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

        # Reads stay open — inference and future runs still consume the frozen bundle.
        resp = self.client.post(self._artifacts_url("/get"), {"path": "train.py"}, format="json")
        assert resp.status_code == status.HTTP_200_OK

    def test_features_sql_must_be_runnable(self):
        runnable = b"SELECT a.person_id AS distinct_id, count() AS c FROM {anchors} a GROUP BY a.person_id"
        resp = self._upload("features.sql", runnable + b" LIMIT 10")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "LIMIT" in str(resp.json())
        assert self._upload("features.sql", runnable).status_code == status.HTTP_201_CREATED

    def test_model_pkl_cannot_be_uploaded(self):
        resp = self._upload("model.pkl", b"\x80\x04")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "model.pkl" in str(resp.json())

    @patch("products.autoresearch.backend.facade.api.MAX_BUNDLE_FILES", 2)
    def test_bundle_file_count_is_capped(self):
        assert self._upload("train.py", b"a").status_code == status.HTTP_201_CREATED
        assert self._upload("predict.py", b"b").status_code == status.HTTP_201_CREATED
        resp = self._upload("eda/notes.md", b"c")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "2 files" in str(resp.json())
        # Overwriting a file that is already in the bundle does not count against the cap.
        assert self._upload("train.py", b"a2").status_code == status.HTTP_201_CREATED

    @parameterized.expand([("upload",), ("delete",)])
    def test_storage_failure_is_a_503(self, action: str):
        self._upload("train.py", b"a")
        storage = self._storage_patcher.new
        with (
            patch.object(storage, "write", side_effect=ObjectStorageError("s3 down")),
            patch.object(storage, "delete", side_effect=ObjectStorageError("s3 down")),
        ):
            if action == "upload":
                resp = self._upload("predict.py", b"b")
            else:
                resp = self.client.post(self._artifacts_url("/delete"), {"path": "train.py"}, format="json")
        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "s3 down" in str(resp.json())

    @parameterized.expand([("list",), ("upload",)])
    def test_artifact_routes_are_scoped_to_the_parent_pipeline(self, action: str):
        other_pipeline = AutoresearchPipeline.objects.create(
            team=self.team, created_by=self.user, name="Other", target_event="$pageview", horizon_days=7
        )
        url = f"{self.base_url}/{other_pipeline.id}/training_runs/{self.training_run.id}/artifacts"
        if action == "list":
            resp = self.client.get(url)
        else:
            resp = self.client.post(f"{url}/upload", {"path": "train.py", "content_base64": "YQ=="}, format="json")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_get_missing_returns_404(self):
        resp = self.client.post(self._artifacts_url("/get"), {"path": "nope.py"}, format="json")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_invalid_path_rejected(self):
        resp = self._upload("../escape.py", b"a")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_base64_rejected(self):
        resp = self.client.post(
            self._artifacts_url("/upload"),
            {"path": "train.py", "content_base64": "not base64!!!"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_training_run_from_other_team_returns_404(self):
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_pipeline = AutoresearchPipeline.objects.create(
            team=other_team, created_by=self.user, name="Other", target_event="$pageview", horizon_days=7
        )
        other_run = AutoresearchTrainingRun.objects.create(pipeline=other_pipeline, status="running")
        # The viewset filters by request team; another team's run is not reachable here.
        resp = self.client.get(f"{self.base_url}/{other_pipeline.id}/training_runs/{other_run.id}/artifacts")
        assert resp.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)


class TestPipelineCreateSerializerValidation(SimpleTestCase):
    # Field- and target-shape validation runs in memory, so these cases never need a DB.
    # The endpoint wiring (bad body -> 400) is covered by the APIBaseTest create tests above.

    def test_required_key_table_covers_every_population_kind(self) -> None:
        # POPULATION_KINDS is derived from the compiler registry in dataset/labeling.py, so a kind
        # registered there reaches this table unannounced. A gap is a 500 on create, not a 400.
        self.assertEqual(set(_POPULATION_KIND_REQUIRED_DAYS), set(POPULATION_KINDS))

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
            ("plateau_iterations_below_min", "plateau_iterations", 0),
            ("success_auc_below_min", "success_auc", -0.1),
            ("success_auc_above_max", "success_auc", 1.5),
        ]
    )
    def test_out_of_range_numeric_field_rejected(self, _name: str, field: str, value: float) -> None:
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
            ("too_many_filters", {"properties": [{"key": "k", "type": "person", "operator": "is_set"}] * 21}),
            (
                "too_many_filter_values",
                {"properties": [{"key": "k", "type": "person", "operator": "exact", "value": list(range(201))}]},
            ),
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

    def test_own_prediction_event_rejected_as_target(self) -> None:
        serializer = self._serializer(target_event="autoresearch_prediction")
        assert not serializer.is_valid()
        assert "target_event" in serializer.errors

    @parameterized.expand(
        [
            ("event_with_filters", {"type": "event", "filters": [{"key": "$current_url"}]}),
            ("legacy_event_shape", {"event": "$pageview", "filters": []}),
            ("unknown_type", {"type": "cohort", "cohort_id": 1}),
            ("not_an_object", "action"),
            ("list", [{"type": "event"}]),
            ("action_id_missing", {"type": "action"}),
            ("action_id_string", {"type": "action", "action_id": "1"}),
            ("action_id_bool", {"type": "action", "action_id": True}),
            ("action_id_zero", {"type": "action", "action_id": 0}),
            ("action_id_overflows_int", {"type": "action", "action_id": 1e400}),
        ]
    )
    def test_unsupported_target_definition_rejected(self, _name: str, definition: Any) -> None:
        serializer = self._serializer(target_definition=definition)
        assert not serializer.is_valid()
        assert "target_definition" in serializer.errors

    @parameterized.expand(
        [
            ("space", "predicted p"),
            ("backtick", "predicted`p"),
            ("braces", "predicted{p}"),
            ("newline", "predicted\np"),
            ("posthog_namespace", "$browser"),
        ]
    )
    def test_invalid_output_person_property_shape_rejected(self, _name: str, value: str) -> None:
        serializer = self._serializer(output_person_property=value)
        assert not serializer.is_valid()
        assert "output_person_property" in serializer.errors
