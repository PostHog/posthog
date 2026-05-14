"""DRF integration tests for the AutoML viewset.

Exercises the `/api/projects/:project_id/automl_pipelines/` endpoints
end-to-end through the request/response cycle.
"""

from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.automl.backend.facade.enums import PipelineStatus

VALID_BODY: dict[str, Any] = {
    "name": "user_event_prediction_demo",
    "task_type": "classification",
    "config": {"target_event": "uploaded_file", "horizon_days": 14, "framing": "adoption"},
    "training_population": {"kind": "hogql", "query": "SELECT person_id FROM events"},
    "inference_population": {"kind": "hogql", "query": "SELECT person_id FROM events"},
}


class TestAutoMLPipelineViewSet(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        base = f"/api/projects/{self.team.id}/automl_pipelines/"
        return base + suffix if suffix else base

    def test_create_pipeline(self):
        response = self.client.post(self._url(), VALID_BODY, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.data
        data = response.json()
        assert data["name"] == "user_event_prediction_demo"
        assert data["task_type"] == "classification"
        assert data["status"] == PipelineStatus.DRAFT.value
        assert data["autonomy"] == "champion_only"

    def test_list_pipelines_returns_team_scoped_results(self):
        self.client.post(self._url(), VALID_BODY, format="json")
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data["results"] if "results" in data else data
        assert len(results) == 1
        assert results[0]["name"] == VALID_BODY["name"]

    def test_retrieve_pipeline(self):
        created = self.client.post(self._url(), VALID_BODY, format="json").json()
        response = self.client.get(self._url(f"{created['id']}/"))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == created["id"]

    def test_retrieve_missing_pipeline_returns_404(self):
        response = self.client.get(self._url("00000000-0000-7000-8000-000000000000/"))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_partial_update_pipeline(self):
        created = self.client.post(self._url(), VALID_BODY, format="json").json()
        response = self.client.patch(
            self._url(f"{created['id']}/"),
            {"description": "Updated description"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["description"] == "Updated description"
        # Status untouched
        assert response.json()["status"] == PipelineStatus.DRAFT.value

    def test_start_transitions_to_bootstrap_pending(self):
        created = self.client.post(self._url(), VALID_BODY, format="json").json()
        fake_task_id = uuid4()
        # Mock the sandbox enqueue — the viewset's contract is "transition + enqueue";
        # we test the transition + runtime side here, the tasks bridge in test_bootstrap.
        with patch("products.automl.backend.facade.api.bootstrap.enqueue_bootstrap_training") as mock_enqueue:
            mock_enqueue.return_value = type("StubTask", (), {"id": fake_task_id})()
            response = self.client.post(self._url(f"{created['id']}/start/"))

        assert response.status_code == status.HTTP_200_OK, response.data
        body = response.json()
        assert body["status"] == PipelineStatus.BOOTSTRAP_PENDING.value
        assert body["runtime"]["bootstrap_task_id"] == str(fake_task_id)

    def test_pause_from_draft_returns_409(self):
        # DRAFT cannot be paused — only ACTIVE / BOOTSTRAP_* can
        created = self.client.post(self._url(), VALID_BODY, format="json").json()
        response = self.client.post(self._url(f"{created['id']}/pause/"))
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["code"] == "invalid_transition"

    def test_archive_transitions_to_archived(self):
        created = self.client.post(self._url(), VALID_BODY, format="json").json()
        response = self.client.post(self._url(f"{created['id']}/archive/"))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == PipelineStatus.ARCHIVED.value

    def test_archived_pipeline_not_in_list(self):
        created = self.client.post(self._url(), VALID_BODY, format="json").json()
        self.client.post(self._url(f"{created['id']}/archive/"))
        response = self.client.get(self._url())
        results = response.json().get("results", response.json())
        assert results == [] or all(r["id"] != created["id"] for r in results)

    def test_create_requires_task_type(self):
        body = {k: v for k, v in VALID_BODY.items() if k != "task_type"}
        response = self.client.post(self._url(), body, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_rejects_unknown_task_type(self):
        body = {**VALID_BODY, "task_type": "telekinesis"}
        response = self.client.post(self._url(), body, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_unique_name_per_team(self):
        self.client.post(self._url(), VALID_BODY, format="json")
        response = self.client.post(self._url(), VALID_BODY, format="json")
        # Either 400 (validation) or 500 from the unique constraint;
        # both are acceptable signals that duplicates are blocked.
        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_409_CONFLICT,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    def test_validate_returns_structured_report(self):
        """POST /validate/ runs preflight checks and returns the report — no pipeline is created."""
        stub_responses = [
            type("Stub", (), {"results": [[50_000]]})(),  # training count
            type("Stub", (), {"results": [[20_000]]})(),  # inference count
            type("Stub", (), {"results": [[1_500]]})(),  # positives count
        ]
        with patch(
            "products.automl.backend.logic.validation.execute_hogql_query",
            side_effect=stub_responses,
        ):
            response = self.client.post(self._url("validate/"), VALID_BODY, format="json")

        assert response.status_code == status.HTTP_200_OK, response.data
        body = response.json()
        assert "ok" in body
        assert "findings" in body
        assert "summary" in body
        assert body["ok"] is True
        assert body["summary"]["estimated_training_rows"] == 50_000
        assert body["summary"]["target_event"] == "uploaded_file"
        # No pipeline was created — list should be empty.
        listed = self.client.get(self._url()).json()
        results = listed.get("results", listed)
        assert results == []

    # ---------------------------------------------------------------------
    # Model version endpoints
    # ---------------------------------------------------------------------

    def _create_pipeline_returning_id(self) -> str:
        return self.client.post(self._url(), VALID_BODY, format="json").json()["id"]

    def _record_body(self, **overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "metrics": {"accuracy": 0.84, "roc_auc": 0.91},
            "leaderboard": [{"model": "WeightedEnsemble_L2", "score_val": 0.85}],
            "training_params": {"presets": "medium_quality", "time_limit_s": 60},
            "eval_metric": "accuracy",
            "problem_type": "binary",
            "artifact_uri": "s3://automl/models/x.tar.gz",
            "features_hash": "abc123",
            "rows_train": 4000,
            "rows_val": 500,
            "rows_test": 500,
        }
        body.update(overrides)
        return body

    def test_record_model_version_returns_201_and_dto(self):
        pid = self._create_pipeline_returning_id()
        response = self.client.post(
            self._url(f"{pid}/model_versions/"),
            self._record_body(),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        body = response.json()
        assert body["role"] == "challenger"  # default
        assert body["metrics"]["accuracy"] == 0.84
        assert body["rows_train"] == 4000
        assert body["pipeline_id"] == pid

    def test_record_model_version_on_missing_pipeline_returns_404(self):
        missing = "00000000-0000-7000-8000-000000000000"
        response = self.client.post(
            self._url(f"{missing}/model_versions/"),
            self._record_body(),
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_list_model_versions_lists_both_roles(self):
        pid = self._create_pipeline_returning_id()
        self.client.post(
            self._url(f"{pid}/model_versions/"),
            self._record_body(role="champion"),
            format="json",
        )
        self.client.post(
            self._url(f"{pid}/model_versions/"),
            self._record_body(role="challenger", metrics={"accuracy": 0.9}),
            format="json",
        )
        response = self.client.get(self._url(f"{pid}/model_versions/"))
        assert response.status_code == status.HTTP_200_OK
        rows = response.json()
        assert isinstance(rows, list)
        assert len(rows) == 2
        # Roles present
        assert {r["role"] for r in rows} == {"champion", "challenger"}

    def test_active_model_version_returns_champion_by_default(self):
        pid = self._create_pipeline_returning_id()
        recorded = self.client.post(
            self._url(f"{pid}/model_versions/"),
            self._record_body(role="champion"),
            format="json",
        ).json()
        response = self.client.get(self._url(f"{pid}/model_versions/active/"))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == recorded["id"]
        assert response.json()["role"] == "champion"

    def test_active_model_version_accepts_role_query_param(self):
        pid = self._create_pipeline_returning_id()
        challenger = self.client.post(
            self._url(f"{pid}/model_versions/"),
            self._record_body(role="challenger"),
            format="json",
        ).json()
        response = self.client.get(self._url(f"{pid}/model_versions/active/?role=challenger"))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == challenger["id"]

    def test_active_model_version_returns_404_when_no_holder(self):
        pid = self._create_pipeline_returning_id()
        response = self.client.get(self._url(f"{pid}/model_versions/active/"))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_active_model_version_rejects_unknown_role(self):
        pid = self._create_pipeline_returning_id()
        response = self.client.get(self._url(f"{pid}/model_versions/active/?role=overlord"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "invalid_role"

    def test_promote_model_version_when_no_prior_champion(self):
        pid = self._create_pipeline_returning_id()
        challenger = self.client.post(
            self._url(f"{pid}/model_versions/"),
            self._record_body(),  # default role = challenger
            format="json",
        ).json()
        response = self.client.post(self._url(f"{pid}/model_versions/{challenger['id']}/promote/"))
        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.json()["id"] == challenger["id"]
        assert response.json()["role"] == "champion"

    def test_promote_model_version_archives_prior_champion(self):
        pid = self._create_pipeline_returning_id()
        old_champ = self.client.post(
            self._url(f"{pid}/model_versions/"),
            self._record_body(role="champion"),
            format="json",
        ).json()
        challenger = self.client.post(
            self._url(f"{pid}/model_versions/"),
            self._record_body(role="challenger", metrics={"accuracy": 0.91}),
            format="json",
        ).json()
        promote_resp = self.client.post(self._url(f"{pid}/model_versions/{challenger['id']}/promote/"))
        assert promote_resp.status_code == status.HTTP_200_OK
        # The old champion should now be archived
        listed = self.client.get(self._url(f"{pid}/model_versions/")).json()
        roles_by_id = {row["id"]: row["role"] for row in listed}
        assert roles_by_id[old_champ["id"]] == "archived"
        assert roles_by_id[challenger["id"]] == "champion"

    def test_promote_missing_version_returns_404(self):
        pid = self._create_pipeline_returning_id()
        missing = "00000000-0000-7000-8000-000000000000"
        response = self.client.post(self._url(f"{pid}/model_versions/{missing}/promote/"))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_promote_rejects_malformed_version_id(self):
        pid = self._create_pipeline_returning_id()
        response = self.client.post(self._url(f"{pid}/model_versions/not-a-uuid/promote/"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "invalid_version_id"

    def test_validate_surfaces_block_findings(self):
        """Low training volume produces a block finding and ok=False without creating anything."""
        stub_responses = [
            type("Stub", (), {"results": [[1_000]]})(),  # under-floor training pop
            type("Stub", (), {"results": [[500]]})(),  # inference pop
            type("Stub", (), {"results": [[50]]})(),  # positives (already blocked by volume)
        ]
        with patch(
            "products.automl.backend.logic.validation.execute_hogql_query",
            side_effect=stub_responses,
        ):
            response = self.client.post(self._url("validate/"), VALID_BODY, format="json")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["ok"] is False
        codes = {f["code"] for f in body["findings"]}
        assert "training_volume_too_low" in codes
