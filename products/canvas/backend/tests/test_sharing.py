import json
from typing import Any

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.api.test.test_sharing import mock_exporter_template
from posthog.models import SharingConfiguration
from posthog.models.scoping import team_scope
from posthog.models.user import User

from products.canvas.backend.models import Canvas, CanvasBuild
from products.canvas.backend.tests.test_canvas_api import CanvasAPIBaseTest
from products.tasks.backend.models import Channel

EXPORTED_DATA_OPEN = '<script id="posthog-exported-data" type="application/json">'


class CanvasSharingTestBase(CanvasAPIBaseTest):
    def _sharing_url(self, canvas_id: str) -> str:
        return f"/api/projects/{self.team.id}/canvases/{canvas_id}/sharing"

    def _publish_ready(self, canvas_id: str, code: str | None = None) -> CanvasBuild:
        with team_scope(self.team.id):
            head = Canvas.objects.get(id=canvas_id).current_source_version_id
        response = self._publish(
            canvas_id,
            self._project(code) if code else None,
            expected_current_version_id=str(head) if head else None,
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        with team_scope(self.team.id):
            canvas = Canvas.objects.get(id=canvas_id)
            build = canvas.builds.order_by("-created_at").first()
            assert build is not None
            build.status = CanvasBuild.STATUS_READY
            build.artifact_object_prefix = f"canvas_artifact/team_{self.team.id}/{canvas_id}/{build.id}"
            build.manifest = {
                "entryHtml": "index.html",
                "assets": [{"path": "index.html", "contentHash": "a" * 64, "sizeBytes": 1, "contentType": "text/html"}],
            }
            build.finished_at = timezone.now()
            build.save(update_fields=["status", "artifact_object_prefix", "manifest", "finished_at"])
            canvas.published_build = build
            canvas.save(update_fields=["published_build"])
        return build

    def _enable_sharing(self, canvas_id: str) -> str:
        response = self.client.patch(self._sharing_url(canvas_id), {"enabled": True})
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()["access_token"]

    def _shared_payload(self, access_token: str) -> dict[str, Any]:
        @mock_exporter_template
        def fetch(test: "CanvasSharingTestBase") -> dict[str, Any]:
            response = test.client.get(f"/shared/{access_token}")
            assert response.status_code == status.HTTP_200_OK, response.content
            body = response.content.decode()
            start = body.index(EXPORTED_DATA_OPEN) + len(EXPORTED_DATA_OPEN)
            return json.loads(body[start : body.index("</script>", start)])

        return fetch(self)


class TestCanvasSharingApi(CanvasSharingTestBase):
    def test_enabling_sharing_serves_the_published_artifact_publicly(self):
        canvas_id = self._create_canvas()
        self._publish_ready(canvas_id)

        access_token = self._enable_sharing(canvas_id)

        with team_scope(self.team.id):
            assert str(SharingConfiguration.objects.get(access_token=access_token).canvas_id) == canvas_id
        self.client.logout()
        with self.settings(CANVAS_ARTIFACT_ORIGIN="https://canvas.example.com"):
            payload = self._shared_payload(access_token)
        assert payload["canvas"]["id"] == canvas_id
        assert payload["canvas"]["published"] is True
        assert payload["canvas"]["artifact_url"].startswith("https://canvas.example.com/canvas-artifacts/")
        assert payload["canvas"]["artifact_url"].endswith("/index.html")

    def test_public_link_keeps_the_build_captured_when_sharing_was_turned_on(self):
        canvas_id = self._create_canvas()
        first = self._publish_ready(canvas_id)
        access_token = self._enable_sharing(canvas_id)
        second = self._publish_ready(canvas_id, code="export default function C() { return 2 }")
        settings_only = self.client.patch(
            self._sharing_url(canvas_id), {"settings": {"allowForking": True}}, format="json"
        )
        assert settings_only.status_code == status.HTTP_200_OK, settings_only.json()

        detail = self.client.get(f"/api/projects/{self.team.id}/canvases/{canvas_id}/").json()
        assert detail["published_build_id"] == str(second.id)
        assert detail["shared_build_id"] == str(first.id)
        self.client.logout()
        with self.settings(CANVAS_ARTIFACT_ORIGIN="https://canvas.example.com"):
            payload = self._shared_payload(access_token)
        assert payload["canvas"]["published"] is True
        assert payload["canvas"]["artifact_url"] is not None

    @parameterized.expand([("after turning it off", True), ("while it is on", False)])
    def test_enabling_again_moves_the_link_to_the_latest_build(self, _name: str, turn_off_first: bool):
        canvas_id = self._create_canvas()
        self._publish_ready(canvas_id)
        self._enable_sharing(canvas_id)
        second = self._publish_ready(canvas_id, code="export default function C() { return 2 }")

        if turn_off_first:
            off = self.client.patch(self._sharing_url(canvas_id), {"enabled": False})
            assert off.status_code == status.HTTP_200_OK, off.json()
            with team_scope(self.team.id):
                assert Canvas.objects.get(id=canvas_id).shared_build_id is None
        self._enable_sharing(canvas_id)

        with team_scope(self.team.id):
            assert Canvas.objects.get(id=canvas_id).shared_build_id == second.id

    @parameterized.expand(
        [
            ("grid", Canvas.KIND_GRID, "This kind of canvas can't be shared publicly yet."),
            ("unpublished", Canvas.KIND_FREEFORM, "Publish the canvas before sharing it."),
        ]
    )
    def test_canvas_without_a_build_to_capture_cannot_be_shared(self, _name: str, kind: str, detail: str):
        canvas_id = self._create_canvas(kind=kind)

        response = self.client.patch(self._sharing_url(canvas_id), {"enabled": True})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["detail"] == detail
        assert not SharingConfiguration.objects.filter(team=self.team, enabled=True).exists()

    @parameterized.expand([("deleted",), ("grid",)])
    def test_public_page_refuses_a_canvas_that_stopped_being_shareable(self, case: str):
        canvas_id = self._create_canvas()
        self._publish_ready(canvas_id)
        access_token = self._enable_sharing(canvas_id)
        with team_scope(self.team.id):
            canvas = Canvas.objects.get(id=canvas_id)
            if case == "deleted":
                canvas.deleted = True
            else:
                canvas.kind = Canvas.KIND_GRID
            canvas.save()

        self.client.logout()
        response = self.client.get(f"/shared/{access_token}")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_someone_elses_personal_canvas_cannot_be_shared(self):
        owner = User.objects.create_and_join(self.organization, "owner@example.com", None)
        with team_scope(self.team.id):
            personal = Channel.objects.create(
                team=self.team, name="me", channel_type=Channel.ChannelType.PERSONAL, created_by=owner
            )
            canvas = Canvas.objects.create(team=self.team, channel=personal, name="Private", created_by=owner)

        response = self.client.patch(self._sharing_url(str(canvas.id)), {"enabled": True})

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert not SharingConfiguration.objects.filter(team=self.team, canvas=canvas).exists()

    def test_refresh_rotates_the_token_and_keeps_the_canvas(self):
        canvas_id = self._create_canvas()
        build = self._publish_ready(canvas_id)
        old_token = self._enable_sharing(canvas_id)

        response = self.client.post(f"{self._sharing_url(canvas_id)}/refresh")

        assert response.status_code == status.HTTP_200_OK, response.json()
        new_token = response.json()["access_token"]
        assert new_token != old_token
        with team_scope(self.team.id):
            new_config = SharingConfiguration.objects.get(access_token=new_token)
            assert str(new_config.canvas_id) == canvas_id
            assert new_config.enabled is True
            assert SharingConfiguration.objects.get(access_token=old_token).expires_at is not None
            assert Canvas.objects.get(id=canvas_id).shared_build_id == build.id
