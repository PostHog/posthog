import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team

from products.autoresearch.backend.inference.sandbox import MaterializedData
from products.autoresearch.backend.models import AutoresearchPipeline, AutoresearchTrainingRun
from products.autoresearch.backend.testing import TeamScopedTestMixin
from products.tasks.backend.facade.sandbox import ExecutionResult, SandboxNotRunningError

VALID_FEATURE_SQL = "SELECT a.person_id AS distinct_id, count() AS pv FROM {anchors} a GROUP BY a.person_id"


class _FakeSandbox:
    def __init__(self, exit_code: int = 0, raises: Exception | None = None):
        self.writes: dict[str, bytes] = {}
        self._exit_code = exit_code
        self._raises = raises

    def write_file(self, path: str, payload: bytes) -> ExecutionResult:
        if self._raises is not None:
            raise self._raises
        self.writes[path] = payload
        return ExecutionResult(stdout="", stderr="boom" if self._exit_code else "", exit_code=self._exit_code)


def _rows(fold: int, labels: list[int], cols: list[str]) -> list[dict]:
    return [
        {"distinct_id": f"p{fold}{i}", "__label": label, "__fold": fold, **dict.fromkeys(cols, i)}
        for i, label in enumerate(labels)
    ]


def _materialized(
    train_labels: tuple[int, ...] = (1, 0),
    holdout_labels: tuple[int, ...] = (0, 1),
    feature_cols: list[str] | None = None,
) -> MaterializedData:
    cols = feature_cols or ["pv", "uploads"]
    return MaterializedData(
        feature_cols=cols,
        train_rows=_rows(1, list(train_labels), cols),
        holdout_rows=_rows(0, list(holdout_labels), cols),
    )


class TestMaterializeFeatures(TeamScopedTestMixin, APIBaseTest):
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

    def _materialize(self, run, *, task_run=None, materialized=None, sandbox=None):
        with (
            patch("products.tasks.backend.facade.sandbox.get_sandbox_class_for_sandbox_id") as mock_resolve,
            patch(
                "products.autoresearch.backend.inference.sandbox.materialize_training_data",
                return_value=materialized or _materialized(),
            ),
            patch(
                "products.tasks.backend.facade.api.get_task_run",
                return_value=task_run or self._fake_task_run(run),
            ),
        ):
            mock_resolve.return_value.get_by_id.return_value = sandbox or _FakeSandbox()
            resp = self.client.post(self._url(run), {"features_sql": VALID_FEATURE_SQL}, format="json")
        return resp, mock_resolve

    def test_writes_parquet_and_returns_paths(self):
        run = self._run(task_run_id=uuid.uuid4())
        fake_sandbox = _FakeSandbox()

        resp, mock_resolve = self._materialize(run, sandbox=fake_sandbox)
        assert resp.status_code == status.HTTP_200_OK, resp.json()
        body = resp.json()
        assert body["n_train"] == 2
        assert body["n_holdout"] == 2
        assert body["n_features"] == 2
        assert body["feature_cols"] == ["pv", "uploads"]
        # All four parquet files land in one per-request directory under the framework-controlled base.
        directory = body["train_features_path"].rsplit("/", 1)[0]
        assert directory.startswith("/tmp/workspace/autoresearch/data/")
        assert set(fake_sandbox.writes.keys()) == {
            f"{directory}/train_features.parquet",
            f"{directory}/train_labels.parquet",
            f"{directory}/holdout_features.parquet",
            f"{directory}/holdout_labels.parquet",
        }
        assert {body[k].rsplit("/", 1)[0] for k in body if k.endswith("_path")} == {directory}
        mock_resolve.assert_called_once_with("sb-123")
        mock_resolve.return_value.get_by_id.assert_called_once_with("sb-123")

    def test_each_request_gets_its_own_directory(self):
        run = self._run(task_run_id=uuid.uuid4())
        first, _ = self._materialize(run)
        second, _ = self._materialize(run)
        assert first.json()["train_features_path"] != second.json()["train_features_path"]

    @parameterized.expand(
        [
            ("state_names_another_run", {"autoresearch_training_run_id": "other", "sandbox_id": "sb-123"}),
            ("state_is_not_an_object", ["not", "a", "dict"]),
        ]
    )
    def test_rejects_sandbox_not_owned_by_run(self, _name: str, state):
        run = self._run(task_run_id=uuid.uuid4())
        resp, mock_resolve = self._materialize(run, task_run=MagicMock(state=state))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "does not belong" in str(resp.json()).lower()
        mock_resolve.return_value.get_by_id.assert_not_called()

    def test_sandbox_write_failure_is_a_400(self):
        run = self._run(task_run_id=uuid.uuid4())
        resp, _ = self._materialize(
            run, sandbox=_FakeSandbox(raises=SandboxNotRunningError("gone", {}, RuntimeError("gone"), capture=False))
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "gone" in str(resp.json())

    def test_over_wide_feature_matrix_is_a_400(self):
        run = self._run(task_run_id=uuid.uuid4())
        resp, _ = self._materialize(run, materialized=_materialized(feature_cols=[f"f{i}" for i in range(513)]))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "column cap" in str(resp.json())

    @parameterized.expand(
        [
            ("no_holdout_rows", (1, 0), (), "too small"),
            ("single_class_holdout", (1, 0), (0,), "holdout set has only one label class"),
            ("single_class_training", (1, 1), (0, 1), "training set has only one label class"),
        ]
    )
    def test_rejects_unscorable_split(self, _name: str, train_labels, holdout_labels, message: str):
        run = self._run(task_run_id=uuid.uuid4())
        fake_sandbox = _FakeSandbox()
        resp, _ = self._materialize(run, materialized=_materialized(train_labels, holdout_labels), sandbox=fake_sandbox)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert message in str(resp.json())
        assert fake_sandbox.writes == {}

    def test_is_scoped_to_the_parent_pipeline(self):
        other_pipeline = AutoresearchPipeline.objects.create(
            team=self.team, created_by=self.user, name="Other", target_event="$pageview", horizon_days=7
        )
        run = self._run(task_run_id=uuid.uuid4())
        resp = self.client.post(
            self._url(run, pipeline=other_pipeline), {"features_sql": VALID_FEATURE_SQL}, format="json"
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_needs_the_query_scope(self):
        run = self._run(task_run_id=uuid.uuid4())
        self.client.logout()
        write_only = self.create_personal_api_key_with_scopes(["autoresearch:write"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {write_only}")
        resp, _ = self._materialize(run)
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        with_query = self.create_personal_api_key_with_scopes(["autoresearch:write", "query:read"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {with_query}")
        resp, _ = self._materialize(run)
        assert resp.status_code == status.HTTP_200_OK, resp.json()
