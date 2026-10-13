from datetime import timedelta
from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from rest_framework import status

from posthog.models.scoping import team_scope

from products.canvas.backend.error_reports import DATA_DRIFT_ERROR_TYPE
from products.canvas.backend.facade.testing import create_canvas
from products.canvas.backend.logic.data_dependencies import check_canvas_data, run_data_dependency_checks
from products.canvas.backend.logic.runtime import prepare_fix_request
from products.canvas.backend.models import Canvas, CanvasBuild, CanvasDataCheck, CanvasSourceVersion
from products.event_definitions.backend.models.event_definition import EventDefinition
from products.event_definitions.backend.models.property_definition import PropertyDefinition
from products.tasks.backend.models import Channel

DECLARED_DATA: dict[str, Any] = {
    "events": ["$pageview", "signup completed"],
    "properties": [{"name": "plan", "type": "person"}, {"name": "$current_url", "type": "event"}],
    "tables": ["stripe_charges"],
}


class CanvasDataDependenciesBaseTest(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        with team_scope(self.team.id):
            self.channel = Channel.objects.create(team=self.team, name="general", created_by=self.user)

    def _canvas_with_data(self, data: dict | None = DECLARED_DATA, *, build: bool = False) -> Canvas:
        canvas_id = create_canvas(
            team_id=self.team.id, channel_id=self.channel.id, name="Launch board", created_by_id=self.user.id
        )
        with team_scope(self.team.id):
            version = CanvasSourceVersion.objects.create(
                team_id=self.team.id,
                canvas_id=canvas_id,
                source_hash="a" * 64,
                source_object_key=f"canvases/test/{canvas_id}/source.json",
                source_size=2,
                task_id=UUID(int=7),
                created_by_id=self.user.id,
                capabilities={"posthog": {"data": data} if data is not None else {}, "network": {"origins": []}},
            )
            canvas = Canvas.objects.get(id=canvas_id)
            canvas.current_source_version = version
            if build:
                canvas.published_build = CanvasBuild.objects.create(
                    team_id=self.team.id,
                    canvas=canvas,
                    source_version=version,
                    status=CanvasBuild.STATUS_READY,
                    artifact_object_prefix="prefix",
                    manifest={"entryHtml": "index.html", "capabilities": version.capabilities},
                )
            canvas.save()
        return canvas


class TestCanvasDataCheck(CanvasDataDependenciesBaseTest):
    @patch("products.canvas.backend.logic.data_dependencies.all_queryable_table_names", return_value={})
    def test_check_records_every_declared_item_the_project_no_longer_has(self, _tables) -> None:
        canvas = self._canvas_with_data()
        EventDefinition.objects.create(team=self.team, name="$pageview")
        PropertyDefinition.objects.create(team=self.team, name="plan", type=PropertyDefinition.Type.PERSON)
        # Same name, wrong type: a person property does not satisfy an event property dependency.
        PropertyDefinition.objects.create(team=self.team, name="$current_url", type=PropertyDefinition.Type.PERSON)

        check = check_canvas_data(canvas)

        assert check.status == CanvasDataCheck.STATUS_DRIFT
        assert check.missing == {
            "events": ["signup completed"],
            "properties": [{"name": "$current_url", "type": "event"}],
            "tables": ["stripe_charges"],
        }
        assert check.source_version_id == canvas.current_source_version_id

    @patch(
        "products.canvas.backend.logic.data_dependencies.all_queryable_table_names",
        return_value={UUID(int=1): "stripe_charges"},
    )
    def test_check_is_ok_when_everything_declared_exists(self, _tables) -> None:
        canvas = self._canvas_with_data()
        for name in DECLARED_DATA["events"]:
            EventDefinition.objects.create(team=self.team, name=name)
        PropertyDefinition.objects.create(team=self.team, name="plan", type=PropertyDefinition.Type.PERSON)
        PropertyDefinition.objects.create(team=self.team, name="$current_url", type=PropertyDefinition.Type.EVENT)

        check = check_canvas_data(canvas)

        assert check.status == CanvasDataCheck.STATUS_OK
        assert check.missing == {"events": [], "properties": [], "tables": []}

    @patch("products.canvas.backend.logic.data_dependencies.all_queryable_table_names", return_value={})
    def test_nightly_run_checks_only_canvases_that_declare_data_and_updates_in_place(self, _tables) -> None:
        declaring = self._canvas_with_data()
        self._canvas_with_data(data=None)
        earlier = timezone.now() - timedelta(days=1)
        with team_scope(self.team.id):
            CanvasDataCheck.objects.create(
                team_id=self.team.id,
                canvas=declaring,
                status=CanvasDataCheck.STATUS_OK,
                missing={"events": [], "properties": [], "tables": []},
                checked_at=earlier,
            )

        counts = run_data_dependency_checks()

        assert counts == {"checked": 1, "drifted": 1}
        checks = list(CanvasDataCheck.objects.unscoped().filter(team_id=self.team.id))
        assert len(checks) == 1
        assert checks[0].canvas_id == declaring.id
        assert checks[0].status == CanvasDataCheck.STATUS_DRIFT
        assert checks[0].checked_at > earlier

    @patch("products.canvas.backend.logic.data_dependencies.all_queryable_table_names", return_value={})
    def test_fix_request_for_data_drift_names_the_missing_items(self, _tables) -> None:
        canvas = self._canvas_with_data(build=True)
        check_canvas_data(canvas)
        assert canvas.published_build_id is not None

        fix = prepare_fix_request(self.team.id, canvas.id, canvas.published_build_id, DATA_DRIFT_ERROR_TYPE)

        assert fix.error_type == DATA_DRIFT_ERROR_TYPE
        assert fix.task_id == UUID(int=7)
        assert "signup completed" in fix.prompt
        assert "stripe_charges" in fix.prompt
        assert "$current_url" in fix.prompt


class TestCanvasDataCheckApi(CanvasDataDependenciesBaseTest):
    def _get(self, canvas_id):
        return self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/data_check/")

    @patch("products.canvas.backend.logic.data_dependencies.all_queryable_table_names", return_value={})
    def test_data_check_reports_unchecked_then_the_latest_result(self, _tables) -> None:
        canvas = self._canvas_with_data()

        before = self._get(canvas.id)
        assert before.status_code == status.HTTP_200_OK, before.json()
        assert before.json() == {
            "status": "unchecked",
            "checked_at": None,
            "missing": {"events": [], "properties": [], "tables": []},
        }

        check_canvas_data(canvas)
        after = self._get(canvas.id)
        assert after.status_code == status.HTTP_200_OK, after.json()
        assert after.json()["status"] == "drift"
        assert after.json()["missing"]["events"] == ["$pageview", "signup completed"]
        assert after.json()["checked_at"] is not None
