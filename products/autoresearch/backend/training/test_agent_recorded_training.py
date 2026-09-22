from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team

from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchSuggestion,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.presentation.views.serializers import (
    AGENT_DESCRIPTION_MAX_LENGTH,
    MODEL_SPEC_MAX_BYTES,
    OBJECT_JSON_MAX_BYTES,
    CompleteTrainingRunSerializer,
    RecordIterationSerializer,
)
from products.autoresearch.backend.testing import TeamScopedTestMixin
from products.autoresearch.backend.training import artifacts
from products.autoresearch.backend.training.ingestion import handle_task_run_completed
from products.autoresearch.backend.training.promotion import PromotionError, complete_training_run
from products.tasks.backend.models import TaskRun as TaskRunModel  # tach-ignore

VALID_FEATURE_SQL = (
    "SELECT a.person_id AS distinct_id, countIf(e.event = '$pageview') AS pv "
    "FROM {anchors} a LEFT JOIN events e ON e.person_id = a.person_id "
    "GROUP BY a.person_id, a.cutoff_ts"
)
VALID_RECIPE = {"feature_sql": VALID_FEATURE_SQL, "feature_transforms": []}
VALID_SPEC = {"model_class": "sklearn.linear_model.LogisticRegression", "model_params": {"C": 1.0}}


class TestAgentRecordedTraining(TeamScopedTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self._flag_patcher = patch(
            "products.autoresearch.backend.access.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self._flag_patcher.start()
        self.addCleanup(self._flag_patcher.stop)
        self.pipeline = AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="Test Pipeline",
            target_event="$pageview",
            horizon_days=7,
            iteration_budget=50,
            iteration_budget_remaining=50,
        )
        self.runs_url = f"/api/projects/{self.team.pk}/autoresearch/{self.pipeline.pk}/training_runs"

    def _open_run(self, *, iteration_budget: int | None = None) -> str:
        body = {"iteration_budget": iteration_budget} if iteration_budget else {}
        resp = self.client.post(f"{self.runs_url}/", body, format="json")
        assert resp.status_code == status.HTTP_201_CREATED, resp.json()
        return resp.json()["id"]

    def _record(
        self,
        run_id: str,
        *,
        number: int,
        status_value: str = "kept",
        holdout: float = 0.8,
        spec: dict[str, Any] | None = None,
        recipe: dict[str, Any] | None = None,
        runs_url: str | None = None,
    ) -> Any:
        return self.client.post(
            f"{runs_url or self.runs_url}/{run_id}/iterations/",
            {
                "iteration_number": number,
                "recipe_snapshot": recipe or VALID_RECIPE,
                "model_spec": spec or VALID_SPEC,
                "status": status_value,
                "holdout_score": holdout,
                "agent_description": "test iteration",
            },
            format="json",
        )

    def test_open_training_run(self):
        resp = self.client.post(f"{self.runs_url}/", {"iteration_budget": 7}, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["status"] == "running"
        assert data["iteration_budget"] == 7
        run = AutoresearchTrainingRun.objects.get(pk=data["id"], team_id=self.team.pk)
        assert run.pipeline.pk == self.pipeline.pk
        assert run.started_at is not None

    def test_record_iteration_creates_row(self):
        run_id = self._open_run()
        resp = self._record(run_id, number=0)
        assert resp.status_code == status.HTTP_201_CREATED, resp.json()
        assert AutoresearchIteration.objects.filter(training_run_id=UUID(run_id), iteration_number=0).exists()

    def test_record_iteration_links_parent_suggestion_and_marks_acted_on(self):
        suggestion = AutoresearchSuggestion.objects.create(
            pipeline=self.pipeline,
            created_by=self.user,
            prompt="try a calibrated logistic regression",
            priority=AutoresearchSuggestion.Priority.TRY_NEXT,
            source=AutoresearchSuggestion.Source.USER,
        )
        run_id = self._open_run()
        resp = self.client.post(
            f"{self.runs_url}/{run_id}/iterations/",
            {
                "iteration_number": 0,
                "recipe_snapshot": VALID_RECIPE,
                "model_spec": VALID_SPEC,
                "status": "kept",
                "holdout_score": 0.9,
                "agent_description": "acting on the steer",
                "parent_suggestion": str(suggestion.id),
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.json()
        iteration = AutoresearchIteration.objects.get(training_run_id=UUID(run_id), iteration_number=0)
        assert str(iteration.parent_suggestion_id) == str(suggestion.id)
        # Spawning an iteration from a suggestion advances it to acted_on for the UI feedback loop.
        suggestion.refresh_from_db()
        assert suggestion.status == "acted_on"
        assert str(iteration.id) in [str(i) for i in suggestion.iterations.values_list("id", flat=True)]
        # A re-send that omits the field keeps the attribution; an explicit null clears it.
        assert self._record(run_id, number=0, holdout=0.95).status_code == status.HTTP_201_CREATED
        iteration.refresh_from_db()
        assert str(iteration.parent_suggestion_id) == str(suggestion.id)
        resp = self.client.post(
            f"{self.runs_url}/{run_id}/iterations/",
            {
                "iteration_number": 0,
                "recipe_snapshot": VALID_RECIPE,
                "model_spec": VALID_SPEC,
                "status": "kept",
                "parent_suggestion": None,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.json()
        iteration.refresh_from_db()
        assert iteration.parent_suggestion_id is None

    def test_record_iteration_rejects_foreign_parent_suggestion(self):
        other_pipeline = AutoresearchPipeline.objects.create(
            team=self.team, created_by=self.user, name="Other", target_event="$pageview", horizon_days=7
        )
        foreign = AutoresearchSuggestion.objects.create(
            pipeline=other_pipeline, created_by=self.user, prompt="foreign", source=AutoresearchSuggestion.Source.USER
        )
        run_id = self._open_run()
        resp = self.client.post(
            f"{self.runs_url}/{run_id}/iterations/",
            {
                "iteration_number": 0,
                "recipe_snapshot": VALID_RECIPE,
                "model_spec": VALID_SPEC,
                "status": "kept",
                "holdout_score": 0.9,
                "parent_suggestion": str(foreign.id),
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_record_iteration_accepts_any_model_class(self):
        # model_class is informational at recording time — the agent's real model runs
        # as arbitrary code in a sandbox. The allowlist is enforced only at the legacy
        # in-process inference importlib site, not here.
        run_id = self._open_run()
        resp = self._record(run_id, number=0, spec={"model_class": "xgboost.XGBClassifier", "model_params": {}})
        assert resp.status_code == status.HTTP_201_CREATED, resp.json()
        assert AutoresearchIteration.objects.filter(training_run_id=UUID(run_id)).exists()

    def test_record_iteration_still_requires_model_class(self):
        run_id = self._open_run()
        resp = self._record(run_id, number=0, spec={"model_params": {}})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_record_iteration_rejects_feature_sql_without_person_id(self):
        run_id = self._open_run()
        resp = self._record(run_id, number=0, recipe={"feature_sql": "SELECT count() AS c FROM events"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "person_id" in str(resp.json())

    def test_record_iteration_is_idempotent_on_number(self):
        run_id = self._open_run()
        self._record(run_id, number=0, holdout=0.7)
        self._record(run_id, number=0, holdout=0.9)
        rows = AutoresearchIteration.objects.filter(training_run_id=UUID(run_id), iteration_number=0)
        assert rows.count() == 1
        row = rows.first()
        assert row is not None and row.holdout_score == 0.9

    def test_record_iteration_refuses_a_new_number_past_the_budget(self):
        run_id = self._open_run(iteration_budget=1)
        assert self._record(run_id, number=0, holdout=0.7).status_code == status.HTTP_201_CREATED
        assert self._record(run_id, number=0, holdout=0.9).status_code == status.HTTP_201_CREATED
        resp = self._record(run_id, number=1)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "iteration budget" in str(resp.json())
        assert AutoresearchIteration.objects.filter(training_run_id=UUID(run_id)).count() == 1

    def test_write_actions_are_bound_to_the_pipeline_in_the_url(self):
        other_pipeline = AutoresearchPipeline.objects.create(
            team=self.team, created_by=self.user, name="Other", target_event="$pageview", horizon_days=7
        )
        other_runs_url = f"/api/projects/{self.team.pk}/autoresearch/{other_pipeline.pk}/training_runs"
        run_id = self._open_run()
        self._record(run_id, number=0)

        assert self._record(run_id, number=1, runs_url=other_runs_url).status_code == status.HTTP_404_NOT_FOUND
        resp = self.client.post(f"{other_runs_url}/{run_id}/complete/", {}, format="json")
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        run = AutoresearchTrainingRun.objects.get(pk=run_id, team_id=self.team.pk)
        assert run.status == AutoresearchTrainingRun.Status.RUNNING
        assert run.iterations.count() == 1

    def test_record_iteration_rejects_when_run_not_running(self):
        run_id = self._open_run()
        self._record(run_id, number=0)
        self.client.post(f"{self.runs_url}/{run_id}/complete/", {}, format="json")
        resp = self._record(run_id, number=1)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_complete_promotes_cold_start_champion(self):
        run_id = self._open_run()
        self._record(run_id, number=0, status_value="discarded", holdout=0.7)
        self._record(run_id, number=1, status_value="kept", holdout=0.82)
        resp = self.client.post(f"{self.runs_url}/{run_id}/complete/", {}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["status"] == "completed"
        assert data["best_holdout_score"] == 0.82
        champion = AutoresearchModel.objects.get(pipeline=self.pipeline, role=AutoresearchModel.Role.CHAMPION)
        assert champion.holdout_score == 0.82
        assert champion.model_recipe["model_class"] == "sklearn.linear_model.LogisticRegression"

    def test_complete_keeps_weaker_model_as_challenger(self):
        # First run promotes a strong champion.
        run1 = self._open_run()
        self._record(run1, number=0, status_value="kept", holdout=0.85)
        self.client.post(f"{self.runs_url}/{run1}/complete/", {}, format="json")
        # Second run's best iteration is weaker — must not steal the champion.
        run2 = self._open_run()
        self._record(run2, number=0, status_value="kept", holdout=0.80)
        self.client.post(f"{self.runs_url}/{run2}/complete/", {}, format="json")
        assert (
            AutoresearchModel.objects.filter(pipeline=self.pipeline, role=AutoresearchModel.Role.CHAMPION).count() == 1
        )
        champion = AutoresearchModel.objects.get(pipeline=self.pipeline, role=AutoresearchModel.Role.CHAMPION)
        assert champion.holdout_score == 0.85
        assert AutoresearchModel.objects.filter(
            pipeline=self.pipeline, role=AutoresearchModel.Role.CHALLENGER, holdout_score=0.80
        ).exists()

    def test_complete_writes_backend_derived_summary(self):
        run_id = self._open_run()
        self._record(run_id, number=0, status_value="kept", holdout=0.75)
        self._record(run_id, number=1, status_value="discarded", holdout=0.70)
        self._record(
            run_id,
            number=2,
            status_value="kept",
            holdout=0.82,
            spec={"model_class": "xgboost.XGBClassifier", "model_params": {}},
        )
        resp = self.client.post(f"{self.runs_url}/{run_id}/complete/", {}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        summary = resp.json()["summary"]
        assert summary["target_event"] == "$pageview"
        assert summary["best_holdout_score"] == 0.82
        assert summary["champion_promoted"] is True
        assert summary["champion_model_class"] == "xgboost.XGBClassifier"
        # kept iterations are ranked highest-AUC first; discarded land in dead_ends.
        assert [it["iteration_number"] for it in summary["kept_ladder"]] == [2, 0]
        assert [it["iteration_number"] for it in summary["dead_ends"]] == [1]
        # Backend leaves the two judgment fields empty when the agent does not supply them.
        assert summary["recommended_next"] == ""
        assert summary["distillation"] == ""

    def test_complete_persists_agent_summary_enrichment(self):
        run_id = self._open_run()
        self._record(run_id, number=0, status_value="kept", holdout=0.8)
        resp = self.client.post(
            f"{self.runs_url}/{run_id}/complete/",
            {"distillation": "log1p of counts won", "recommended_next": "try session recency"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        summary = resp.json()["summary"]
        assert summary["distillation"] == "log1p of counts won"
        assert summary["recommended_next"] == "try session recency"
        run = AutoresearchTrainingRun.objects.get(pk=run_id, team_id=self.team.pk)
        assert run.summary["recommended_next"] == "try session recency"

    def test_complete_that_loses_the_race_to_failure_is_refused(self):
        run_id = self._open_run()
        self._record(run_id, number=0)

        def fail_first(training_run, **kwargs):
            AutoresearchTrainingRun.objects.filter(pk=training_run.pk).update(
                status=AutoresearchTrainingRun.Status.FAILED
            )
            return {"promoted": False}

        with patch("products.autoresearch.backend.training.promotion.complete_training_run", side_effect=fail_first):
            resp = self.client.post(f"{self.runs_url}/{run_id}/complete/", {}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "failed" in str(resp.json())

    def test_complete_with_no_iterations_is_refused(self):
        # Completing an empty run used to mark it COMPLETED with no champion, stranding a
        # BOOTSTRAPPING pipeline with nothing to score and no safety-net retry.
        run_id = self._open_run()
        run = AutoresearchTrainingRun.objects.get(pk=run_id, team_id=self.team.pk)
        with self.assertRaises(PromotionError):
            complete_training_run(run)
        run.refresh_from_db()
        assert run.status == AutoresearchTrainingRun.Status.RUNNING
        assert not AutoresearchModel.objects.filter(pipeline=self.pipeline).exists()

    def test_signal_handler_uses_agent_recorded_path_when_iterations_exist(self):
        # Agent opens a run and records an iteration via the new MCP write path.
        run_id = self._open_run()
        self._record(run_id, number=0, status_value="kept", holdout=0.81)

        # Simulate the TaskRun post_save signal firing on completion.
        fake_task_run = MagicMock()
        fake_task_run.state = {"autoresearch_training_run_id": run_id}
        fake_task_run.status = TaskRunModel.Status.COMPLETED
        fake_task_run.error_message = ""
        fake_task_run.id = UUID("00000000-0000-0000-0000-000000000000")
        fake_task_run.team_id = self.team.pk
        fake_task_run.output = None  # no set_output blob — agent recorded via tools
        # Ingestion only trusts a task run that the training run was bound to at dispatch.
        AutoresearchTrainingRun.objects.filter(pk=run_id, team_id=self.team.pk).update(task_run_id=fake_task_run.id)

        handle_task_run_completed(fake_task_run)

        run = AutoresearchTrainingRun.objects.get(pk=run_id, team_id=self.team.pk)
        assert run.status == AutoresearchTrainingRun.Status.COMPLETED
        assert run.best_holdout_score == 0.81
        assert AutoresearchModel.objects.filter(
            pipeline=self.pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            holdout_score=0.81,
        ).exists()

    def test_cross_team_isolation(self):
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org, name="Other team")
        other_pipeline = AutoresearchPipeline.objects.create(
            team=other_team, created_by=self.user, name="Other", target_event="$pageview", horizon_days=7
        )
        resp = self.client.post(
            f"/api/projects/{self.team.pk}/autoresearch/{other_pipeline.pk}/training_runs/", {}, format="json"
        )
        # Pipeline belongs to another team — must not be reachable through this project.
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert not AutoresearchTrainingRun.objects.filter(pipeline=other_pipeline).exists()
        resp = self.client.get(f"/api/projects/{self.team.pk}/autoresearch/{other_pipeline.pk}/training_runs/history/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_complete_records_artifact_prefix_when_bundle_uploaded(self):
        fake_storage = _InMemoryStorage()
        with patch.object(artifacts, "object_storage", fake_storage):
            run_id = self._open_run()
            self._record(run_id, number=0, status_value="kept", holdout=0.82)

            run = AutoresearchTrainingRun.objects.get(pk=run_id, team_id=self.team.pk)
            prefix = artifacts.bundle_prefix(
                team_id=self.team.pk, pipeline_id=str(self.pipeline.pk), training_run_id=str(run.pk)
            )
            artifacts.write_bundle(
                prefix,
                artifacts.ArtifactBundle(
                    train_py="print('train')",
                    predict_py="print('predict')",
                    # Promotion refuses a bundle whose SQL differs from the selected iteration's recorded one.
                    features_sql=VALID_FEATURE_SQL,
                ),
            )

            resp = self.client.post(f"{self.runs_url}/{run_id}/complete/", {}, format="json")
            assert resp.status_code == status.HTTP_200_OK

        champion = AutoresearchModel.objects.get(pipeline=self.pipeline, role=AutoresearchModel.Role.CHAMPION)
        assert champion.artifact_prefix == prefix
        assert champion.metrics["artifact_bundle"] is True
        # model_recipe is derived from the winning iteration's recorded model_spec.
        assert champion.model_recipe["model_class"] == "sklearn.linear_model.LogisticRegression"

    def test_complete_without_bundle_leaves_artifact_prefix_empty(self):
        run_id = self._open_run()
        self._record(run_id, number=0, status_value="kept", holdout=0.7)
        resp = self.client.post(f"{self.runs_url}/{run_id}/complete/", {}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        champion = AutoresearchModel.objects.get(pipeline=self.pipeline, role=AutoresearchModel.Role.CHAMPION)
        assert champion.artifact_prefix == ""
        assert champion.metrics["artifact_bundle"] is False


class TestTrainingRunHistory(TeamScopedTestMixin, APIBaseTest):
    """The cross-run learning-memory read-back endpoint (training_runs/history)."""

    def setUp(self):
        super().setUp()
        self._flag_patcher = patch(
            "products.autoresearch.backend.access.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self._flag_patcher.start()
        self.addCleanup(self._flag_patcher.stop)
        self.pipeline = AutoresearchPipeline.objects.create(
            team=self.team, created_by=self.user, name="Main", target_event="downloaded_file", horizon_days=30
        )

    def _runs_url(self, pipeline) -> str:
        return f"/api/projects/{self.team.pk}/autoresearch/{pipeline.pk}/training_runs"

    def _completed_run(self, pipeline, *, iterations, distillation="", recommended_next="") -> str:
        runs_url = self._runs_url(pipeline)
        run_id = self.client.post(f"{runs_url}/", {}, format="json").json()["id"]
        for number, (status_value, holdout, desc) in enumerate(iterations):
            self.client.post(
                f"{runs_url}/{run_id}/iterations/",
                {
                    "iteration_number": number,
                    "recipe_snapshot": VALID_RECIPE,
                    "model_spec": VALID_SPEC,
                    "status": status_value,
                    "holdout_score": holdout,
                    "agent_description": desc,
                },
                format="json",
            )
        resp = self.client.post(
            f"{runs_url}/{run_id}/complete/",
            {"distillation": distillation, "recommended_next": recommended_next},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        return run_id

    def _history(self, pipeline=None, **params):
        pipeline = pipeline or self.pipeline
        return self.client.get(f"{self._runs_url(pipeline)}/history/", params)

    def test_history_returns_iteration_trail_for_completed_run(self):
        run_id = self._completed_run(
            self.pipeline,
            iterations=[("discarded", 0.70, "baseline engagement"), ("kept", 0.82, "added file RFM")],
        )
        resp = self._history()
        assert resp.status_code == status.HTTP_200_OK
        runs = resp.json()["runs"]
        assert len(runs) == 1
        run = runs[0]
        assert run["run_id"] == run_id
        assert run["is_current_pipeline"] is True
        assert run["target_event"] == "downloaded_file"
        assert run["best_holdout_score"] == 0.82
        descriptions = [(it["status"], it["holdout_score"], it["agent_description"]) for it in run["iterations"]]
        assert descriptions == [
            ("discarded", 0.70, "baseline engagement"),
            ("kept", 0.82, "added file RFM"),
        ]
        assert run["iterations"][0]["model_spec"]["model_class"] == "sklearn.linear_model.LogisticRegression"
        assert run["iterations"][1]["recipe_snapshot"]["feature_sql"] == VALID_FEATURE_SQL

    def test_history_excludes_runs_that_are_not_completed(self):
        # An open (running) run with a recorded iteration must not surface as history.
        runs_url = self._runs_url(self.pipeline)
        run_id = self.client.post(f"{runs_url}/", {}, format="json").json()["id"]
        self.client.post(
            f"{runs_url}/{run_id}/iterations/",
            {
                "iteration_number": 0,
                "recipe_snapshot": VALID_RECIPE,
                "model_spec": VALID_SPEC,
                "status": "kept",
                "holdout_score": 0.8,
                "agent_description": "in progress",
            },
            format="json",
        )
        resp = self._history()
        assert resp.json()["runs"] == []

    def test_history_includes_same_target_sibling_flagged_not_current(self):
        sibling = AutoresearchPipeline.objects.create(
            team=self.team, created_by=self.user, name="Sibling", target_event="downloaded_file", horizon_days=30
        )
        other_target = AutoresearchPipeline.objects.create(
            team=self.team, created_by=self.user, name="OtherTarget", target_event="$pageview", horizon_days=30
        )
        # An action whose name matches the event is a different outcome, not a sibling.
        same_name_action = AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="SameNameAction",
            target_event="downloaded_file",
            target_definition={"type": "action", "action_id": 42},
            horizon_days=30,
        )
        self._completed_run(sibling, iterations=[("kept", 0.75, "sibling run")])
        self._completed_run(other_target, iterations=[("kept", 0.90, "different target")])
        self._completed_run(same_name_action, iterations=[("kept", 0.91, "same-name action")])
        self._completed_run(self.pipeline, iterations=[("kept", 0.80, "own run")])

        runs = self._history().json()["runs"]
        by_target_desc = {r["iterations"][0]["agent_description"]: r for r in runs}
        # Own run + same-target sibling appear; the different-target pipeline does not.
        assert set(by_target_desc) == {"own run", "sibling run"}
        assert by_target_desc["own run"]["is_current_pipeline"] is True
        assert by_target_desc["sibling run"]["is_current_pipeline"] is False
        # Current pipeline is listed first.
        assert runs[0]["iterations"][0]["agent_description"] == "own run"

    def test_history_respects_limit(self):
        for _ in range(3):
            self._completed_run(self.pipeline, iterations=[("kept", 0.8, "run")])
        # An undated completed run sorts after the dated ones instead of taking the first slot.
        undated = AutoresearchTrainingRun.objects.create(
            pipeline=self.pipeline, status=AutoresearchTrainingRun.Status.COMPLETED, completed_at=None
        )
        assert [r["run_id"] for r in self._history(limit=4).json()["runs"]][-1] == str(undated.id)
        assert len(self._history(limit=2).json()["runs"]) == 2
        assert self._history(limit=0).status_code == status.HTTP_400_BAD_REQUEST
        assert self._history(limit="many").status_code == status.HTTP_400_BAD_REQUEST

    def test_history_includes_distilled_run_summary(self):
        self._completed_run(
            self.pipeline,
            iterations=[("discarded", 0.70, "baseline"), ("kept", 0.82, "winner")],
            distillation="log1p of file counts is the signal",
            recommended_next="try session-recency features",
        )
        summary = self._history().json()["runs"][0]["summary"]
        assert summary["distillation"] == "log1p of file counts is the signal"
        assert summary["recommended_next"] == "try session-recency features"
        assert summary["target_event"] == "downloaded_file"
        assert summary["best_holdout_score"] == 0.82
        assert summary["champion_promoted"] is True
        assert [it["iteration_number"] for it in summary["kept_ladder"]] == [1]
        assert [it["iteration_number"] for it in summary["dead_ends"]] == [0]

    def test_history_excludes_other_teams(self):
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org, name="Other team")
        other_pipeline = AutoresearchPipeline.objects.create(
            team=other_team, created_by=self.user, name="Other", target_event="downloaded_file", horizon_days=30
        )
        # Build a completed run on the other team directly (its API is on a different project route).
        other_run = AutoresearchTrainingRun.objects.create(
            pipeline=other_pipeline, status=AutoresearchTrainingRun.Status.COMPLETED, best_holdout_score=0.99
        )
        AutoresearchIteration.objects.create(
            pipeline=other_pipeline,
            training_run=other_run,
            iteration_number=0,
            recipe_hash="x",
            recipe_snapshot=VALID_RECIPE,
            model_spec=VALID_SPEC,
            holdout_score=0.99,
            status="kept",
            agent_description="leaked",
        )
        self._completed_run(self.pipeline, iterations=[("kept", 0.8, "own")])
        runs = self._history().json()["runs"]
        assert all(r["iterations"][0]["agent_description"] != "leaked" for r in runs)


class TestAgentWriteSerializers(SimpleTestCase):
    @parameterized.expand(
        [
            ("nan_holdout", {"holdout_score": "NaN"}, "holdout_score"),
            ("infinite_train_score", {"train_score": "Infinity"}, "train_score"),
            ("nan_confidence", {"agent_confidence": "nan"}, "agent_confidence"),
            ("iteration_number_past_int32", {"iteration_number": 2**31}, "iteration_number"),
            ("list_shaped_recipe", {"recipe_snapshot": [VALID_FEATURE_SQL]}, "recipe_snapshot"),
            ("string_shaped_spec", {"model_spec": "sklearn.linear_model.LogisticRegression"}, "model_spec"),
            ("non_string_feature_sql", {"recipe_snapshot": {"feature_sql": 123}}, "non_field_errors"),
            (
                "oversized_rationale",
                {"agent_description": "x" * (AGENT_DESCRIPTION_MAX_LENGTH + 1)},
                "agent_description",
            ),
            ("nested_nan_in_spec", {"model_spec": {**VALID_SPEC, "model_params": {"C": float("nan")}}}, "model_spec"),
            ("lone_surrogate_in_recipe", {"recipe_snapshot": {**VALID_RECIPE, "note": "\ud800"}}, "recipe_snapshot"),
            ("boolean_holdout", {"holdout_score": True}, "holdout_score"),
            ("integer_past_float_range", {"holdout_score": 10**400}, "holdout_score"),
            ("string_model_params", {"model_spec": {**VALID_SPEC, "model_params": "bad"}}, "non_field_errors"),
            ("oversized_spec", {"model_spec": {**VALID_SPEC, "pad": "x" * MODEL_SPEC_MAX_BYTES}}, "model_spec"),
            (
                "string_transforms",
                {"recipe_snapshot": {**VALID_RECIPE, "feature_transforms": "bad"}},
                "non_field_errors",
            ),
            ("nul_in_recipe", {"recipe_snapshot": {**VALID_RECIPE, "note": "a\x00b"}}, "recipe_snapshot"),
            (
                "oversized_recipe",
                {"recipe_snapshot": {**VALID_RECIPE, "pad": "x" * OBJECT_JSON_MAX_BYTES}},
                "recipe_snapshot",
            ),
        ]
    )
    def test_record_iteration_rejects(self, _name: str, overrides: dict[str, Any], error_key: str) -> None:
        data = {
            "iteration_number": 0,
            "recipe_snapshot": VALID_RECIPE,
            "model_spec": VALID_SPEC,
            "status": "kept",
            "holdout_score": 0.8,
            **overrides,
        }
        serializer = RecordIterationSerializer(data=data)
        assert not serializer.is_valid()
        assert error_key in serializer.errors, serializer.errors

    def test_complete_rejects_a_non_object_explanation(self) -> None:
        serializer = CompleteTrainingRunSerializer(data={"model_explanation": ["top_features"]})
        assert not serializer.is_valid()
        assert "model_explanation" in serializer.errors


class _InMemoryStorage:
    """In-memory object_storage stand-in for bundle round-trips in tests."""

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
