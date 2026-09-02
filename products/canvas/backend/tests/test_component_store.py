from typing import Any

from parameterized import parameterized
from rest_framework import status

from posthog.models.scoping import team_scope

from products.canvas.backend.models import Canvas, CanvasSourceVersion
from products.canvas.backend.tests.test_canvas_api import CanvasAPIBaseTest

COMPONENT_META: dict[str, Any] = {
    "size": {"defaultW": 2, "defaultH": 1, "minW": 1, "minH": 1},
    "configSchema": {"type": "object", "properties": {"location": {"type": "string"}}},
}


class TestComponentStore(CanvasAPIBaseTest):
    def _component_project(self, **overrides) -> dict[str, Any]:
        return self._project(component=COMPONENT_META, **overrides)

    def test_component_publish_requires_meta(self):
        canvas_id = self._create_canvas(kind="component")
        response = self._publish(canvas_id)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == "invalid_source_project"
        assert any(entry["code"] == "component_meta_missing" for entry in response.json()["diagnostics"])

    def test_component_publish_snapshots_meta_and_lists_it(self):
        canvas_id = self._create_canvas(kind="component", description="Local weather tile")
        response = self._publish(canvas_id, self._component_project())
        assert response.status_code == status.HTTP_200_OK, response.json()
        with team_scope(self.team.id):
            version = CanvasSourceVersion.objects.get(pk=response.json()["current_version_id"])
        assert version.component_meta == COMPONENT_META

        listed = self.client.get(f"/api/projects/{self.team.id}/canvases/?kind=component")
        rows = listed.json()["results"]
        assert [row["id"] for row in rows] == [canvas_id]
        assert rows[0]["kind"] == "component"
        assert rows[0]["description"] == "Local weather tile"
        assert rows[0]["component_meta"] == COMPONENT_META

    def test_freeform_publish_rejects_component_meta(self):
        canvas_id = self._create_canvas()
        response = self._publish(canvas_id, self._component_project())
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert any(entry["code"] == "component_meta_not_allowed" for entry in response.json()["diagnostics"])

    @parameterized.expand(["publish", "edit", "draft", "publish-current-version"])
    def test_grid_canvas_rejects_source_endpoints(self, endpoint: str):
        canvas_id = self._create_canvas(kind="grid")
        response = self.client.post(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/{endpoint}/",
            {"project": self._project(), "operations": [{"path": "src/canvas.tsx", "content": "x"}]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == "wrong_canvas_kind"

    def test_list_filters_by_kind_and_search(self):
        self._create_canvas(name="Plain app")
        weather_id = self._create_canvas(kind="component", name="Weather", description="Shows local weather")
        self._create_canvas(kind="component", name="Kanban", description="Task board")

        by_kind = self.client.get(f"/api/projects/{self.team.id}/canvases/?kind=component")
        assert {row["name"] for row in by_kind.json()["results"]} == {"Weather", "Kanban"}

        by_search = self.client.get(f"/api/projects/{self.team.id}/canvases/?kind=component&search=weather")
        assert [row["id"] for row in by_search.json()["results"]] == [weather_id]

    def test_create_rejects_unknown_kind(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/canvases/",
            {"name": "Bad", "channel_id": str(self.channel.id), "kind": "widget"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_description(self):
        canvas_id = self._create_canvas(kind="component")
        response = self.client.patch(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/",
            {"description": "Shows the local weather for a configured location"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        with team_scope(self.team.id):
            assert Canvas.objects.get(pk=canvas_id).description == "Shows the local weather for a configured location"
