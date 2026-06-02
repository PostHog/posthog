from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models import Organization, Team

from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchTrainingRun,
)

VALID_RECIPE = {
    "feature_sql": "SELECT person_id AS distinct_id, countIf(event = '$pageview') AS pv FROM events GROUP BY person_id",
    "feature_transforms": [],
}
VALID_SPEC = {"model_class": "sklearn.linear_model.LogisticRegression", "model_params": {"C": 1.0}}


class TestAgentRecordedTraining(APIBaseTest):
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

    def _open_run(self) -> str:
        resp = self.client.post(f"{self.runs_url}/", {}, format="json")
        assert resp.status_code == status.HTTP_201_CREATED, resp.json()
        return resp.json()["id"]

    def _record(
        self, run_id: str, *, number: int, status_value: str = "kept", holdout: float = 0.8, spec=None, recipe=None
    ):
        return self.client.post(
            f"{self.runs_url}/{run_id}/iterations/",
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
        run = AutoresearchTrainingRun.objects.get(pk=data["id"])
        assert run.pipeline.pk == self.pipeline.pk
        assert run.started_at is not None

    def test_record_iteration_creates_row(self):
        run_id = self._open_run()
        resp = self._record(run_id, number=0)
        assert resp.status_code == status.HTTP_201_CREATED, resp.json()
        assert AutoresearchIteration.objects.filter(training_run_id=run_id, iteration_number=0).exists()

    def test_record_iteration_accepts_any_model_class(self):
        # model_class is informational at recording time — the agent's real model runs
        # as arbitrary code in a sandbox. The allowlist is enforced only at the legacy
        # in-process inference importlib site, not here.
        run_id = self._open_run()
        resp = self._record(run_id, number=0, spec={"model_class": "xgboost.XGBClassifier", "model_params": {}})
        assert resp.status_code == status.HTTP_201_CREATED, resp.json()
        assert AutoresearchIteration.objects.filter(training_run_id=run_id).exists()

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
        rows = AutoresearchIteration.objects.filter(training_run_id=run_id, iteration_number=0)
        assert rows.count() == 1
        row = rows.first()
        assert row is not None and row.holdout_score == 0.9

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
        run = AutoresearchTrainingRun.objects.get(pk=run_id)
        assert run.summary["recommended_next"] == "try session recency"

    def test_complete_with_no_iterations_writes_skeleton_summary(self):
        run_id = self._open_run()
        resp = self.client.post(f"{self.runs_url}/{run_id}/complete/", {}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        summary = resp.json()["summary"]
        assert summary["best_holdout_score"] is None
        assert summary["champion_promoted"] is False
        assert summary["kept_ladder"] == []
        assert summary["dead_ends"] == []

    def test_signal_handler_uses_agent_recorded_path_when_iterations_exist(self):
        from unittest.mock import MagicMock

        from products.autoresearch.backend.training_ingestion import handle_task_run_completed
        from products.tasks.backend.models import TaskRun as TaskRunModel

        # Agent opens a run and records an iteration via the new MCP write path.
        run_id = self._open_run()
        self._record(run_id, number=0, status_value="kept", holdout=0.81)

        # Simulate the TaskRun post_save signal firing on completion.
        fake_task_run = MagicMock()
        fake_task_run.state = {"autoresearch_training_run_id": run_id}
        fake_task_run.status = TaskRunModel.Status.COMPLETED
        fake_task_run.error_message = ""
        fake_task_run.id = "00000000-0000-0000-0000-000000000000"
        fake_task_run.output = None  # no set_output blob — agent recorded via tools

        handle_task_run_completed(fake_task_run)

        run = AutoresearchTrainingRun.objects.get(pk=run_id)
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
        assert resp.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)
        assert not AutoresearchTrainingRun.objects.filter(pipeline=other_pipeline).exists()

    def test_complete_records_artifact_prefix_when_bundle_uploaded(self):
        from products.autoresearch.backend import artifacts

        fake_storage = _InMemoryStorage()
        with patch.object(artifacts, "object_storage", fake_storage):
            run_id = self._open_run()
            self._record(run_id, number=0, status_value="kept", holdout=0.82)

            run = AutoresearchTrainingRun.objects.get(pk=run_id)
            prefix = artifacts.bundle_prefix(
                team_id=self.team.pk, pipeline_id=str(self.pipeline.pk), training_run_id=str(run.pk)
            )
            artifacts.write_bundle(
                prefix,
                artifacts.ArtifactBundle(
                    train_py="print('train')",
                    predict_py="print('predict')",
                    features_sql="SELECT a.person_id AS distinct_id FROM {anchors} a",
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


class TestTrainingRunHistory(APIBaseTest):
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
        assert resp.status_code == status.HTTP_200_OK, resp.json()
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
        assert resp.status_code == status.HTTP_200_OK, resp.json()
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
        self._completed_run(sibling, iterations=[("kept", 0.75, "sibling run")])
        self._completed_run(other_target, iterations=[("kept", 0.90, "different target")])
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
        assert len(self._history(limit=2).json()["runs"]) == 2
        # Out-of-range limits are clamped, not errored.
        assert self._history(limit=0).status_code == status.HTTP_200_OK
        assert len(self._history(limit=0).json()["runs"]) == 1

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
