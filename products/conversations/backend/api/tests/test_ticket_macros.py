from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.conversations.backend.models import Ticket, TicketMacro
from products.conversations.backend.models.constants import Channel


class TestTicketMacroAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/conversations/macros/"

    def _create(self, **overrides) -> dict:
        payload = {"name": "Cancellation", "body": "Hi {{customer.first_name}}", "shortcut": "cancel"}
        payload.update(overrides)
        response = self.client.post(self.base_url, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    @patch("products.conversations.backend.api.ticket_macros.report_user_action")
    def test_create_lowercases_shortcut_and_logs_activity(self, mock_report):
        data = self._create(shortcut="Cancel")
        assert data["shortcut"] == "cancel"
        assert data["name"] == "Cancellation"
        assert data["usage_count"] == 0
        assert data["last_used_at"] is None
        assert data["created_by"]["id"] == self.user.pk
        assert data["body"] == "Hi {{customer.first_name}}"

        mock_report.assert_called_once()
        assert mock_report.call_args[0][1] == "support macro created"

        entry = ActivityLog.objects.filter(scope="TicketMacro", item_id=data["id"], activity="created").get()
        assert entry.detail is not None
        assert entry.detail["name"] == "Cancellation"

    def test_markdown_escapes_around_variables_are_stored_as_tokens(self):
        escaped = "Hi \\{\\{customer\\.first\\_name\\}\\} What's up\\!"
        data = self._create(body=escaped, shortcut="hi")
        assert data["body"] == "Hi {{customer.first_name}} What's up\\!"
        stored = TicketMacro.objects.for_team(self.team.id).get(pk=data["id"])
        assert stored.body == "Hi {{customer.first_name}} What's up\\!"

        TicketMacro.objects.for_team(self.team.id).filter(pk=stored.id).update(body="Bye \\{\\{customer\\.name\\}\\}")
        response = self.client.get(f"{self.base_url}{stored.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["body"] == "Bye {{customer.name}}"

    def test_list_orders_by_usage(self):
        quiet = self._create(name="Quiet", shortcut="quiet")
        popular = self._create(name="Popular", shortcut="popular")
        TicketMacro.objects.for_team(self.team.id).filter(pk=popular["id"]).update(usage_count=4)

        response = self.client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        assert [row["name"] for row in response.json()["results"]] == ["Popular", "Quiet"]
        assert quiet["id"] != popular["id"]

    def test_blank_shortcuts_do_not_collide(self):
        self._create(name="One", shortcut="")
        self._create(name="Two", shortcut=None)
        assert TicketMacro.objects.for_team(self.team.id).filter(shortcut__isnull=True).count() == 2

    def test_duplicate_shortcut_rejected(self):
        self._create()
        response = self.client.post(
            self.base_url,
            {"name": "Other", "body": "Hello", "shortcut": "cancel"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert TicketMacro.objects.for_team(self.team.id).count() == 1

    def test_same_shortcut_allowed_on_another_team(self):
        self._create()
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        TicketMacro.objects.for_team(team2.id).create(team=team2, name="Theirs", shortcut="cancel", body="Hi")
        assert TicketMacro.objects.for_team(team2.id).filter(shortcut="cancel").exists()

    @parameterized.expand(
        [
            ("spaces", "cancel subscription"),
            ("slash", "/cancel"),
            ("punctuation", "cancel!"),
        ]
    )
    def test_rejects_shortcut_that_is_not_a_slug(self, _label, shortcut):
        response = self.client.post(
            self.base_url,
            {"name": "Bad", "body": "Hello", "shortcut": shortcut},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not TicketMacro.objects.for_team(self.team.id).exists()

    def test_patch_keeps_omitted_body(self):
        created = self._create()
        response = self.client.patch(f"{self.base_url}{created['id']}/", {"name": "Renamed"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Renamed"
        assert response.json()["body"] == created["body"]
        assert response.json()["shortcut"] == "cancel"

    def test_body_edit_is_masked_in_activity_log(self):
        created = self._create()
        response = self.client.patch(f"{self.base_url}{created['id']}/", {"body": "Bye for now"}, format="json")
        assert response.status_code == status.HTTP_200_OK

        entry = ActivityLog.objects.filter(scope="TicketMacro", item_id=created["id"], activity="updated").get()
        assert entry.detail is not None
        body_change = next(change for change in entry.detail["changes"] if change["field"] == "body")
        assert body_change["before"] == "masked"
        assert body_change["after"] == "masked"

    def test_put_not_allowed(self):
        created = self._create()
        response = self.client.put(f"{self.base_url}{created['id']}/", {"name": "Replaced", "body": "x"}, format="json")
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_cannot_read_another_teams_macro(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        other = TicketMacro.objects.for_team(team2.id).create(team=team2, name="Other", body="Secret", shortcut="x")
        response = self.client.get(f"{self.base_url}{other.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(["session", "personal_api_key"])
    def test_used_increments_without_an_audit_row(self, auth):
        created = self._create()
        before = ActivityLog.objects.filter(scope="TicketMacro", item_id=created["id"]).count()
        if auth == "personal_api_key":
            raw_key = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                label="ticket-write",
                user=self.user,
                secure_value=hash_key_value(raw_key),
                scopes=["ticket:write"],
            )
            self.client.logout()
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_key}")

        response = self.client.post(f"{self.base_url}{created['id']}/used/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["usage_count"] == 1
        assert response.json()["last_used_at"] is not None

        again = self.client.post(f"{self.base_url}{created['id']}/used/")
        assert again.json()["usage_count"] == 2
        assert ActivityLog.objects.filter(scope="TicketMacro", item_id=created["id"]).count() == before

    def test_delete(self):
        created = self._create()
        response = self.client.delete(f"{self.base_url}{created['id']}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not TicketMacro.objects.for_team(self.team.id).filter(pk=created["id"]).exists()
        assert ActivityLog.objects.filter(scope="TicketMacro", item_id=created["id"], activity="deleted").exists()

    def test_editor_grant_on_one_ticket_cannot_edit_macros(self):
        created = self._create()
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
        url = f"{self.base_url}{created['id']}/"

        assert self.client.get(self.base_url).status_code == status.HTTP_200_OK
        assert self.client.post(f"{url}used/").status_code == status.HTTP_200_OK
        assert self.client.patch(url, {"body": "Hijacked"}, format="json").status_code == status.HTTP_403_FORBIDDEN
        assert self.client.delete(url).status_code == status.HTTP_403_FORBIDDEN
        assert TicketMacro.objects.for_team(self.team.id).get(pk=created["id"]).body == created["body"]
