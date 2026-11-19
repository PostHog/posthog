from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.conversations.backend.models import AgentOutOfOffice, Ticket
from products.conversations.backend.models.constants import Channel


class TestAgentOutOfOfficeAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/conversations/out_of_office/"
        self.me_url = f"{self.base_url}me/"

    @patch("products.conversations.backend.api.agent_out_of_office.report_user_action")
    def test_set_creates_an_entry_and_logs_activity(self, mock_report):
        response = self.client.post(self.me_url)

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["user"]["email"] == self.user.email
        assert data["since"] is not None
        assert mock_report.call_args[0][1] == "support out of office set"
        entry = ActivityLog.objects.get(scope="AgentOutOfOffice", item_id=data["id"], activity="created")
        assert entry.detail is not None
        assert entry.detail["name"] == self.user.email

    def test_setting_again_keeps_the_original_time(self):
        first = self.client.post(self.me_url).json()

        again = self.client.post(self.me_url)

        assert again.status_code == status.HTTP_200_OK
        assert again.json() == first
        assert AgentOutOfOffice.objects.for_team(self.team.id).count() == 1

    @patch("products.conversations.backend.api.agent_out_of_office.report_user_action")
    def test_clear_deletes_the_entry_and_logs_activity(self, mock_report):
        created = self.client.post(self.me_url).json()

        response = self.client.delete(self.me_url)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not AgentOutOfOffice.objects.for_team(self.team.id).exists()
        assert mock_report.call_args[0][1] == "support out of office cleared"
        assert ActivityLog.objects.filter(scope="AgentOutOfOffice", item_id=created["id"], activity="deleted").exists()

    def test_clear_when_not_away_succeeds_without_activity(self):
        response = self.client.delete(self.me_url)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not ActivityLog.objects.filter(scope="AgentOutOfOffice").exists()

    def test_clear_only_removes_the_callers_own_entry(self):
        teammate = User.objects.create_and_join(self.organization, "teammate@example.com", "password")
        AgentOutOfOffice.objects.for_team(self.team.id).create(team=self.team, user=teammate)
        self.client.post(self.me_url)

        self.client.delete(self.me_url)

        remaining = AgentOutOfOffice.objects.for_team(self.team.id).values_list("user_id", flat=True)
        assert list(remaining) == [teammate.id]

    def test_list_shows_everyone_away_in_this_team_only(self):
        teammate = User.objects.create_and_join(self.organization, "teammate@example.com", "password")
        other_team = Team.objects.create(organization=self.organization, name="Other")
        AgentOutOfOffice.objects.for_team(self.team.id).create(team=self.team, user=teammate)
        AgentOutOfOffice.objects.for_team(other_team.id).create(team=other_team, user=self.user)

        response = self.client.get(self.base_url)

        assert response.status_code == status.HTTP_200_OK
        assert [row["user"]["email"] for row in response.json()["results"]] == ["teammate@example.com"]

    @parameterized.expand([("put",), ("patch",)])
    def test_me_rejects_other_methods(self, method):
        response = getattr(self.client, method)(self.me_url)
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    @parameterized.expand(
        [
            ("read_scope_cannot_set", ["ticket:read"], "post", status.HTTP_403_FORBIDDEN),
            ("read_scope_can_list", ["ticket:read"], "get", status.HTTP_200_OK),
            ("write_scope_can_set", ["ticket:write"], "post", status.HTTP_201_CREATED),
        ]
    )
    def test_personal_api_key_scopes(self, _name, scopes, method, expected):
        raw_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="ticket", user=self.user, secure_value=hash_key_value(raw_key), scopes=scopes
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_key}")

        url = self.base_url if method == "get" else self.me_url
        assert getattr(self.client, method)(url).status_code == expected

    def test_editor_grant_on_one_ticket_cannot_set_out_of_office(self):
        self.organization.available_product_features = [{"key": "access_control", "name": "Access control"}]
        self.organization.save()
        ticket = Ticket.objects.create_with_number(
            team=self.team, channel_source=Channel.WIDGET, widget_session_id="s", distinct_id="d"
        )
        membership = self.user.organization_memberships.get(organization=self.organization)
        AccessControl.objects.create(team=self.team, resource="ticket", access_level="none")
        AccessControl.objects.create(
            team=self.team,
            resource="ticket",
            resource_id=str(ticket.id),
            organization_member=membership,
            access_level="editor",
        )

        assert self.client.post(self.me_url).status_code == status.HTTP_403_FORBIDDEN
