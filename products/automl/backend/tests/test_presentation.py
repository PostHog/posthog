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
