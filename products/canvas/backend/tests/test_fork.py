from typing import Any, cast

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.constants import AvailableFeature
from posthog.models import Organization, SharingConfiguration, Team
from posthog.models.organization import OrganizationMembership
from posthog.models.scoping import team_scope
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.canvas.backend import build_service
from products.canvas.backend.models import Canvas, CanvasBuild, CanvasSourceVersion
from products.canvas.backend.tests.test_sharing import CanvasSharingTestBase
from products.tasks.backend.models import Channel


class TestCanvasFork(CanvasSharingTestBase):
    def _fork(self, body: dict[str, Any], client: Any = None):
        return (client or self.client).post(f"/api/projects/{self.team.id}/canvases/fork/", body, format="json")

    def test_fork_copies_the_published_version_into_the_personal_space(self):
        canvas_id = self._create_canvas(name="Revenue board")
        self._publish_ready(canvas_id)
        with team_scope(self.team.id):
            source = Canvas.objects.get(id=canvas_id)
            source_version = cast(CanvasSourceVersion, cast(CanvasBuild, source.published_build).source_version)

        response = self._fork({"source_canvas_id": canvas_id})

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["id"] != canvas_id
        assert body["name"] == "Revenue board"
        assert body["forked_from_canvas_id"] == canvas_id
        assert body["forked_from_version_id"] == str(source_version.id)
        with team_scope(self.team.id):
            fork = Canvas.objects.get(id=body["id"])
            assert fork.channel.channel_type == Channel.ChannelType.PERSONAL
            assert fork.channel.created_by_id == self.user.id
            fork_version = cast(CanvasSourceVersion, fork.current_source_version)
            assert fork_version.source_hash == source_version.source_hash
            assert fork_version.source_object_key != source_version.source_object_key
            assert build_service.read_source_project(fork_version) == build_service.read_source_project(source_version)
            assert fork.builds.filter(status=CanvasBuild.STATUS_QUEUED).count() == 1
            assert Canvas.objects.get(id=canvas_id).current_source_version_id == source_version.id

    def test_fork_refuses_an_unpublished_canvas(self):
        canvas_id = self._create_canvas()

        response = self._fork({"source_canvas_id": canvas_id})

        assert response.status_code == status.HTTP_409_CONFLICT, response.json()

    def test_fork_refuses_a_canvas_the_caller_cannot_see(self):
        owner = User.objects.create_and_join(self.organization, "owner@example.com", None)
        with team_scope(self.team.id):
            personal = Channel.objects.create(
                team=self.team, name="me", channel_type=Channel.ChannelType.PERSONAL, created_by=owner
            )
            private = Canvas.objects.create(team=self.team, channel=personal, name="Private", created_by=owner)

        response = self._fork({"source_canvas_id": str(private.id)})

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_fork_refuses_a_canvas_the_caller_is_denied_access_to(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save(update_fields=["level"])
        owner = User.objects.create_and_join(self.organization, "owner@example.com", None)
        with team_scope(self.team.id):
            restricted = Canvas.objects.create(
                team=self.team, channel=self.channel, name="Restricted", created_by=owner
            )
        AccessControl.objects.create(
            team=self.team,
            resource="canvas",
            resource_id=str(restricted.id),
            organization_member=self.organization_membership,
            access_level="none",
        )

        response = self._fork({"source_canvas_id": str(restricted.id)})

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("both sources", {"source_canvas_id": "00000000-0000-0000-0000-000000000000", "share_token": "t"}),
            ("no source", {}),
        ]
    )
    def test_fork_needs_exactly_one_source(self, _name: str, body: dict[str, Any]):
        response = self._fork(body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def _shared_canvas(self, *, allow_forking: bool, password_required: bool = False) -> str:
        canvas_id = self._create_canvas(name="Shared board")
        self._publish_ready(canvas_id)
        access_token = self._enable_sharing(canvas_id)
        with team_scope(self.team.id):
            config = SharingConfiguration.objects.get(access_token=access_token)
            config.settings = {"allowForking": allow_forking}
            config.password_required = password_required
            config.save()
        return access_token

    def _other_project_client(self) -> tuple[Any, Team]:
        organization = Organization.objects.create(name="Elsewhere")
        team = Team.objects.create(organization=organization, name="Elsewhere")
        user = User.objects.create_and_join(organization, "elsewhere@example.com", None)

        client = APIClient()
        client.force_login(user)
        return client, team

    def test_share_token_fork_copies_across_projects(self):
        access_token = self._shared_canvas(allow_forking=True)
        client, team = self._other_project_client()

        response = client.post(f"/api/projects/{team.id}/canvases/fork/", {"share_token": access_token}, format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        with team_scope(team.id):
            fork = Canvas.objects.get(id=response.json()["id"])
            assert fork.team_id == team.id
            fork_version = cast(CanvasSourceVersion, fork.current_source_version)
            assert fork_version.source_object_key.startswith(f"canvas_source/team_{team.id}/")

    @parameterized.expand(
        [
            ("copies not allowed", {"allow_forking": False}, status.HTTP_403_FORBIDDEN),
            ("password protected", {"allow_forking": True, "password_required": True}, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_share_token_fork_is_refused(self, _name: str, share: dict[str, Any], expected: int):
        access_token = self._shared_canvas(**share)
        client, team = self._other_project_client()

        response = client.post(f"/api/projects/{team.id}/canvases/fork/", {"share_token": access_token}, format="json")

        assert response.status_code == expected, response.json()
        assert not Canvas.objects.unscoped().filter(team_id=team.id).exists()

    def test_share_token_fork_refuses_a_disabled_share(self):
        access_token = self._shared_canvas(allow_forking=True)
        with team_scope(self.team.id):
            SharingConfiguration.objects.filter(access_token=access_token).update(enabled=False)
        client, team = self._other_project_client()

        response = client.post(f"/api/projects/{team.id}/canvases/fork/", {"share_token": access_token}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
