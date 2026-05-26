import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status

from posthog.models import Organization, Team

from products.autoresearch.backend.models import (
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchRun,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.validation import ValidationResult, ValidationWarning

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


class TestAutoresearchPipelineAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/autoresearch"

    def _make_pipeline(self, **kwargs) -> AutoresearchPipeline:
        defaults = {
            "team": self.team,
            "created_by": self.user,
            "name": "Test Pipeline",
            "target_event": "$pageview",
            "horizon_days": 7,
            "prediction_mode": "adoption",
            "iteration_budget": 50,
            "iteration_budget_remaining": 50,
        }
        defaults.update(kwargs)
        return AutoresearchPipeline.objects.create(**defaults)

    # ──────────────────────────────────────────── CRUD ────────────────────────────────────────────

    def test_create_pipeline(self):
        resp = self.client.post(
            f"{self.base_url}/",
            {"name": "My Pipeline", "target_event": "$signup", "horizon_days": 14, "prediction_mode": "adoption"},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["name"] == "My Pipeline"
        assert data["target_event"] == "$signup"
        assert data["status"] == "draft"
        assert AutoresearchPipeline.objects.filter(team=self.team, name="My Pipeline").exists()

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

    def test_pause_and_resume_pipeline(self):
        pipeline = self._make_pipeline(status=AutoresearchPipeline.Status.RUNNING)
        resp = self.client.post(f"{self.base_url}/{pipeline.id}/pause/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["status"] == "paused"

        resp2 = self.client.post(f"{self.base_url}/{pipeline.id}/resume/")
        assert resp2.status_code == status.HTTP_200_OK
        assert resp2.json()["status"] == "running"

    def test_resume_non_paused_pipeline_returns_400(self):
        pipeline = self._make_pipeline(status=AutoresearchPipeline.Status.RUNNING)
        resp = self.client.post(f"{self.base_url}/{pipeline.id}/resume/")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_archive_pipeline(self):
        pipeline = self._make_pipeline()
        resp = self.client.post(f"{self.base_url}/{pipeline.id}/archive/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["status"] == "archived"
        pipeline.refresh_from_db()
        assert pipeline.status == AutoresearchPipeline.Status.ARCHIVED

    def test_train_archived_pipeline_returns_404(self):
        pipeline = self._make_pipeline(status=AutoresearchPipeline.Status.ARCHIVED)
        # Archived pipelines are excluded from the queryset so the endpoint returns 404
        resp = self.client.post(f"{self.base_url}/{pipeline.id}/train/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_score_archived_pipeline_returns_404(self):
        pipeline = self._make_pipeline(status=AutoresearchPipeline.Status.ARCHIVED)
        resp = self.client.post(f"{self.base_url}/{pipeline.id}/score/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_score_without_champion_returns_400(self):
        pipeline = self._make_pipeline(status=AutoresearchPipeline.Status.RUNNING)
        resp = self.client.post(f"{self.base_url}/{pipeline.id}/score/")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # ─────────────────────────────────────── validate action ──────────────────────────────────────

    @patch("products.autoresearch.backend.api.validate_pipeline_definition", return_value=MOCK_VALIDATION_OK)
    def test_validate_pipeline_success(self, _mock: MagicMock):
        resp = self.client.post(
            f"{self.base_url}/validate/",
            {"target_event": "$signup", "horizon_days": 7, "prediction_mode": "adoption"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["can_proceed"] is True
        assert data["base_rate"] == pytest.approx(0.2)
        assert data["warnings"] == []

    @patch("products.autoresearch.backend.api.validate_pipeline_definition", return_value=MOCK_VALIDATION_ERROR)
    def test_validate_pipeline_with_errors(self, _mock: MagicMock):
        resp = self.client.post(
            f"{self.base_url}/validate/",
            {"target_event": "$rare_event", "horizon_days": 7, "prediction_mode": "adoption"},
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

    def test_start_training(self):
        pipeline = self._make_pipeline()
        training_run = AutoresearchTrainingRun.objects.create(
            pipeline=pipeline,
            status=AutoresearchTrainingRun.Status.RUNNING,
            iteration_budget=50,
        )
        with patch("products.autoresearch.backend.api.run_training", return_value=training_run):
            resp = self.client.post(f"{self.base_url}/{pipeline.id}/train/")

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["status"] == "running"

    # ─────────────────────────────────── nested resources ─────────────────────────────────────────

    def test_list_models_for_pipeline(self):
        pipeline = self._make_pipeline()
        AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            model_recipe={"stub": True},
            recipe_hash="abc123",
            holdout_score=0.7,
        )
        resp = self.client.get(f"{self.base_url}/{pipeline.id}/models/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["count"] == 1
        assert resp.json()["results"][0]["role"] == "champion"

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
