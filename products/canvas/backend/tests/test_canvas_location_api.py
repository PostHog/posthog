from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import Organization
from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.models.user import User

from products.canvas.backend.models import Canvas
from products.canvas.backend.tests.test_canvas_api import CanvasAPIBaseTest
from products.tasks.backend.models import Channel


class TestCanvasLocationAPI(CanvasAPIBaseTest):
    def _location(self, canvas_id: str):
        return self.client.get(f"/api/canvas_locations/{canvas_id}/")

    def test_resolves_a_canvas_in_another_project_of_the_same_organization(self):
        other_team = Team.objects.create(organization=self.organization, name="Second project")
        with team_scope(other_team.id):
            channel = Channel.objects.create(team=other_team, name="general", created_by=self.user)
            canvas = Canvas.objects.create(team=other_team, channel=channel, name="Revenue", created_by=self.user)

        response = self._location(str(canvas.id))

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["project_id"] == other_team.id
        assert body["project_name"] == "Second project"
        assert body["organization_id"] == str(self.organization.id)
        assert body["canvas_name"] == "Revenue"
        assert body["channel_id"] == str(channel.id)
        assert body["url"].endswith(f"/code/canvas/{channel.id}/{canvas.id}")

    # Every one of these has to be indistinguishable, or the endpoint tells a caller which
    # canvas ids exist in projects they cannot read.
    @parameterized.expand(
        [
            ("unknown_id",),
            ("team_the_user_cannot_access",),
            ("another_users_personal_channel",),
            ("soft_deleted",),
        ]
    )
    def test_hides_every_unreachable_canvas_behind_the_same_404(self, case: str):
        canvas_id = self._canvas_id_for(case)

        response = self._location(canvas_id)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["code"] == "not_found"

    def _canvas_id_for(self, case: str) -> str:
        if case == "unknown_id":
            return "01a020ca-0000-7000-8000-000000000000"

        if case == "team_the_user_cannot_access":
            other_org = Organization.objects.create(name="Someone else")
            other_team = Team.objects.create(organization=other_org, name="Theirs")
            outsider = User.objects.create_and_join(other_org, "outsider@example.com", None)
            with team_scope(other_team.id):
                channel = Channel.objects.create(team=other_team, name="general", created_by=outsider)
                canvas = Canvas.objects.create(team=other_team, channel=channel, name="Theirs", created_by=outsider)
            return str(canvas.id)

        if case == "another_users_personal_channel":
            teammate = User.objects.create_and_join(self.organization, "teammate@example.com", None)
            with team_scope(self.team.id):
                personal = Channel.objects.create(
                    team=self.team,
                    name=Channel.PERSONAL_CHANNEL_NAME,
                    channel_type=Channel.ChannelType.PERSONAL,
                    created_by=teammate,
                )
                canvas = Canvas.objects.create(team=self.team, channel=personal, name="Private", created_by=teammate)
            return str(canvas.id)

        with team_scope(self.team.id):
            canvas = Canvas.objects.create(
                team=self.team, channel=self.channel, name="Gone", created_by=self.user, deleted=True
            )
        return str(canvas.id)

    # Guards the permission classes, not DRF: without IsAuthenticated this endpoint would
    # hand out the location of any canvas to anyone.
    def test_denies_an_unauthenticated_caller(self):
        with team_scope(self.team.id):
            canvas = Canvas.objects.create(team=self.team, channel=self.channel, name="Mine", created_by=self.user)
        self.client.logout()

        response = self._location(str(canvas.id))

        assert response.status_code == status.HTTP_403_FORBIDDEN
