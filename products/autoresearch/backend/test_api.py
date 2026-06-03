import base64

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status

from posthog.models import Organization, Team

from products.actions.backend.models.action import Action
from products.autoresearch.backend.models import (
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchRun,
    AutoresearchSuggestion,
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
            {"target_event": "$signup", "horizon_days": 7},
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


class TestAutoresearchSuggestionAPI(APIBaseTest):
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


class _InMemoryStorage:
    """In-memory stand-in for object_storage so artifact endpoints don't need MinIO."""

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


class TestAutoresearchArtifactAPI(APIBaseTest):
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
            "products.autoresearch.backend.artifacts.object_storage",
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
        resp = self._upload("train.py", b"print('train')")
        assert resp.status_code == status.HTTP_201_CREATED, resp.content
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
