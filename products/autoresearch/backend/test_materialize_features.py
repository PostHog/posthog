import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status

from posthog.models import Organization, Team

from products.autoresearch.backend.models import AutoresearchPipeline, AutoresearchTrainingRun
from products.autoresearch.backend.sandbox_inference import MaterializedData
from products.tasks.backend.facade.sandbox import ExecutionResult

VALID_FEATURE_SQL = "SELECT person_id AS distinct_id, countIf(event = '$pageview') AS pv FROM events GROUP BY person_id"


class _FakeSandbox:
    """Records the parquet files the action writes into the sandbox."""

    def __init__(self, exit_code: int = 0):
        self.writes: dict[str, bytes] = {}
        self._exit_code = exit_code

    def write_file(self, path: str, payload: bytes) -> ExecutionResult:
        self.writes[path] = payload
        return ExecutionResult(stdout="", stderr="boom" if self._exit_code else "", exit_code=self._exit_code)


def _materialized() -> MaterializedData:
    return MaterializedData(
        feature_cols=["pv", "uploads"],
        train_rows=[{"distinct_id": "p1", "pv": 5, "uploads": 1, "__label": 1, "__fold": 1}],
        holdout_rows=[{"distinct_id": "p3", "pv": 2, "uploads": 0, "__label": 0, "__fold": 0}],
    )


class TestMaterializeFeatures(APIBaseTest):
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

    def _run(self, *, status_value=AutoresearchTrainingRun.Status.RUNNING, task_run_id=None) -> AutoresearchTrainingRun:
        return AutoresearchTrainingRun.objects.create(
            pipeline=self.pipeline, status=status_value, task_run_id=task_run_id
        )

    def _url(self, run: AutoresearchTrainingRun, pipeline=None) -> str:
        pipeline = pipeline or self.pipeline
        return f"/api/projects/{self.team.pk}/autoresearch/{pipeline.pk}/training_runs/{run.id}/materialize-features/"

    def _fake_task_run(self, run: AutoresearchTrainingRun, *, sandbox_id="sb-123"):
        return MagicMock(state={"autoresearch_training_run_id": str(run.id), "sandbox_id": sandbox_id})

    def test_rejects_non_running_run(self):
        run = self._run(status_value=AutoresearchTrainingRun.Status.COMPLETED)
        resp = self.client.post(self._url(run), {"features_sql": VALID_FEATURE_SQL}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "running" in str(resp.json()).lower()

    def test_rejects_feature_sql_without_person_id(self):
        run = self._run()
        resp = self.client.post(self._url(run), {"features_sql": "SELECT 1 AS x FROM events"}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "person_id" in str(resp.json())

    def test_rejects_run_without_sandbox(self):
        run = self._run(task_run_id=None)
        resp = self.client.post(self._url(run), {"features_sql": VALID_FEATURE_SQL}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "sandbox" in str(resp.json()).lower()

    def test_is_team_scoped(self):
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org, name="Other")
        other_pipeline = AutoresearchPipeline.objects.create(
            team=other_team, created_by=self.user, name="Other", target_event="$pageview", horizon_days=7
        )
        other_run = AutoresearchTrainingRun.objects.create(
            pipeline=other_pipeline, status=AutoresearchTrainingRun.Status.RUNNING
        )
        # Address another team's run through our team's URL — must not resolve.
        resp = self.client.post(
            self._url(other_run, pipeline=other_pipeline), {"features_sql": VALID_FEATURE_SQL}, format="json"
        )
        assert resp.status_code in (status.HTTP_404_NOT_FOUND, status.HTTP_400_BAD_REQUEST)

    @patch("products.autoresearch.backend.api.Sandbox")
    @patch("products.autoresearch.backend.api.materialize_training_data")
    @patch("products.tasks.backend.models.TaskRun.objects.get")
    def test_writes_parquet_and_returns_paths(self, mock_task_get, mock_materialize, mock_sandbox):
        run = self._run(task_run_id=uuid.uuid4())
        mock_task_get.return_value = self._fake_task_run(run)
        mock_materialize.return_value = _materialized()
        fake_sandbox = _FakeSandbox()
        mock_sandbox.get_by_id.return_value = fake_sandbox

        resp = self.client.post(self._url(run), {"features_sql": VALID_FEATURE_SQL}, format="json")
        assert resp.status_code == status.HTTP_200_OK, resp.json()
        body = resp.json()
        assert body["n_train"] == 1
        assert body["n_holdout"] == 1
        assert body["n_features"] == 2
        assert body["feature_cols"] == ["pv", "uploads"]
        # All four parquet files were written into the sandbox under the framework-controlled dir.
        assert set(fake_sandbox.writes.keys()) == {
            "/tmp/workspace/autoresearch/data/train_features.parquet",
            "/tmp/workspace/autoresearch/data/train_labels.parquet",
            "/tmp/workspace/autoresearch/data/holdout_features.parquet",
            "/tmp/workspace/autoresearch/data/holdout_labels.parquet",
        }
        assert body["train_features_path"] == "/tmp/workspace/autoresearch/data/train_features.parquet"
        mock_sandbox.get_by_id.assert_called_once_with("sb-123")

    @patch("products.autoresearch.backend.api.Sandbox")
    @patch("products.autoresearch.backend.api.materialize_training_data")
    @patch("products.tasks.backend.models.TaskRun.objects.get")
    def test_rejects_sandbox_not_owned_by_run(self, mock_task_get, mock_materialize, mock_sandbox):
        run = self._run(task_run_id=uuid.uuid4())
        # TaskRun state points at a DIFFERENT training run — must be rejected.
        mock_task_get.return_value = MagicMock(
            state={"autoresearch_training_run_id": str(uuid.uuid4()), "sandbox_id": "sb-123"}
        )
        mock_materialize.return_value = _materialized()
        mock_sandbox.get_by_id.return_value = _FakeSandbox()

        resp = self.client.post(self._url(run), {"features_sql": VALID_FEATURE_SQL}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "does not belong" in str(resp.json()).lower()
        mock_sandbox.get_by_id.assert_not_called()
