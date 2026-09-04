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

    def _publish_ready(self, canvas_id: str) -> CanvasBuild:
        response = self._publish(canvas_id)
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

    def test_unpublished_canvas_shares_without_an_artifact_url(self):
        canvas_id = self._create_canvas()
        access_token = self._enable_sharing(canvas_id)

        self.client.logout()
        payload = self._shared_payload(access_token)

        assert payload["canvas"]["published"] is False
        assert payload["canvas"]["artifact_url"] is None

    def test_grid_canvas_cannot_be_shared(self):
        canvas_id = self._create_canvas(kind=Canvas.KIND_GRID)

        response = self.client.patch(self._sharing_url(canvas_id), {"enabled": True})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert not SharingConfiguration.objects.filter(team=self.team, enabled=True).exists()

    @parameterized.expand([("deleted",), ("grid",)])
    def test_public_page_refuses_a_canvas_that_stopped_being_shareable(self, case: str):
        canvas_id = self._create_canvas()
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
