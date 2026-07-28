from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient, APIRequestFactory

from posthog.models.team.team import Team

from products.conversations.backend.api.ticket_views import TicketViewSerializer
from products.conversations.backend.models import TicketView, TicketViewFavorite


class TestTicketViewAPI(APIBaseTest):
    base_url: str

    def setUp(self):
        super().setUp()
        self.base_url = f"/api/environments/{self.team.pk}/conversations/views/"

    def _valid_payload(self, **overrides) -> dict:
        defaults = {
            "name": "Urgent open tickets",
            "filters": {"status": ["new", "open"], "priority": ["high"]},
        }
        defaults.update(overrides)
        return defaults

    def _create_via_api(self, **overrides) -> dict:
        response = self.client.post(self.base_url, self._valid_payload(**overrides), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    # --- CRUD ---

    @patch("products.conversations.backend.api.ticket_views.report_user_action")
    def test_create(self, mock_report):
        data = self._create_via_api()
        assert data["name"] == "Urgent open tickets"
        assert data["filters"] == {"status": ["new", "open"], "priority": ["high"]}
        assert data["short_id"] is not None
        assert data["created_by"]["id"] == self.user.pk

        mock_report.assert_called_once()
        assert mock_report.call_args[0][1] == "ticket view created"
        assert mock_report.call_args[0][2]["name"] == "Urgent open tickets"
        assert mock_report.call_args[0][2]["has_filters"] is True

    def test_list(self):
        self._create_via_api(name="View 1")
        self._create_via_api(name="View 2")

        response = self.client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 2
        assert {r["name"] for r in results} == {"View 1", "View 2"}

    def test_retrieve(self):
        created = self._create_via_api()

        response = self.client.get(f"{self.base_url}{created['short_id']}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["short_id"] == created["short_id"]
        assert response.json()["name"] == "Urgent open tickets"

    @patch("products.conversations.backend.api.ticket_views.report_user_action")
    def test_delete(self, mock_report):
        created = self._create_via_api()
        mock_report.reset_mock()

        response = self.client.delete(f"{self.base_url}{created['short_id']}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not TicketView.objects.filter(pk=created["id"]).exists()

        mock_report.assert_called_once()
        assert mock_report.call_args[0][1] == "ticket view deleted"

    @patch("products.conversations.backend.api.ticket_views.report_user_action")
    def test_update_name_keeps_short_id_and_filters(self, mock_report):
        created = self._create_via_api()
        mock_report.reset_mock()

        response = self.client.patch(
            f"{self.base_url}{created['short_id']}/",
            {"name": "Renamed", "short_id": "hijacked"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "Renamed"
        assert data["short_id"] == created["short_id"]
        assert data["filters"] == created["filters"]

        mock_report.assert_called_once()
        assert mock_report.call_args[0][1] == "ticket view updated"

    def test_put_not_allowed(self):
        created = self._create_via_api()
        response = self.client.put(
            f"{self.base_url}{created['short_id']}/",
            {"name": "Replaced"},
            format="json",
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert TicketView.objects.get(pk=created["id"]).filters == created["filters"]

    def test_update_filters_keeps_name(self):
        created = self._create_via_api()

        new_filters = {"status": ["resolved"], "assignee": {"type": "role", "id": "abc"}}
        response = self.client.patch(
            f"{self.base_url}{created['short_id']}/",
            {"filters": new_filters},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["filters"] == new_filters
        assert response.json()["name"] == created["name"]

    # --- Filters are optional ---

    def test_create_with_empty_filters(self):
        data = self._create_via_api(filters={})
        assert data["filters"] == {}

    def test_create_with_no_filters(self):
        response = self.client.post(self.base_url, {"name": "Minimal view"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["filters"] == {}

    def test_create_with_complex_filters(self):
        filters = {
            "status": ["new", "open"],
            "priority": ["high", "medium"],
            "channel": "slack",
            "sla": "breached",
            "assignee": "user:1",
            "tags": ["bug", "urgent"],
            "dateFrom": "-7d",
            "dateTo": None,
            "sorting": {"columnKey": "updated_at", "order": -1},
        }
        data = self._create_via_api(filters=filters)
        assert data["filters"] == filters

    # --- Validation ---

    @parameterized.expand(
        [
            ("missing_name", {"filters": {}}),
            ("blank_name", {"name": "", "filters": {}}),
        ]
    )
    def test_create_rejects_invalid_name(self, _label, payload):
        response = self.client.post(self.base_url, payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # --- Read-only fields ---

    def test_short_id_ignored_on_create(self):
        data = self._create_via_api(short_id="custom123")
        assert data["short_id"] != "custom123"

    # --- Team isolation ---

    def test_list_only_own_team(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        TicketView.objects.create(team=team2, name="Other team view", created_by=self.user)
        self._create_via_api(name="My view")

        response = self.client.get(self.base_url)
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["name"] == "My view"

    def test_cannot_retrieve_other_teams_view(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        other_view = TicketView.objects.create(team=team2, name="Other", created_by=self.user)

        response = self.client.get(f"{self.base_url}{other_view.short_id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_cannot_update_other_teams_view(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        other_view = TicketView.objects.create(team=team2, name="Other", created_by=self.user)

        response = self.client.patch(f"{self.base_url}{other_view.short_id}/", {"name": "Hacked"}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        other_view.refresh_from_db()
        assert other_view.name == "Other"

    def test_cannot_delete_other_teams_view(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        other_view = TicketView.objects.create(team=team2, name="Other", created_by=self.user)

        response = self.client.delete(f"{self.base_url}{other_view.short_id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert TicketView.objects.filter(pk=other_view.id).exists()

    # --- Personal favorites ---

    def test_favorite_and_unfavorite(self):
        created = self._create_via_api()

        response = self.client.patch(f"{self.base_url}{created['short_id']}/", {"is_favorited": True}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["is_favorited"] is True
        assert (
            TicketViewFavorite.objects.for_team(self.team.pk)
            .filter(ticket_view_id=created["id"], user=self.user)
            .count()
            == 1
        )

        # Idempotent: favoriting again doesn't create a second row
        self.client.patch(f"{self.base_url}{created['short_id']}/", {"is_favorited": True}, format="json")
        assert (
            TicketViewFavorite.objects.for_team(self.team.pk)
            .filter(ticket_view_id=created["id"], user=self.user)
            .count()
            == 1
        )

        response = self.client.patch(f"{self.base_url}{created['short_id']}/", {"is_favorited": False}, format="json")
        assert response.json()["is_favorited"] is False
        assert (
            not TicketViewFavorite.objects.for_team(self.team.pk)
            .filter(ticket_view_id=created["id"], user=self.user)
            .exists()
        )

    @parameterized.expand([("favorited", True), ("not_favorited", False)])
    def test_create_with_favorited_flag(self, _label, favorited):
        data = self._create_via_api(is_favorited=favorited)
        assert data["is_favorited"] is favorited
        assert (
            TicketViewFavorite.objects.for_team(self.team.pk).filter(ticket_view_id=data["id"], user=self.user).exists()
            is favorited
        )

    def test_favorites_are_personal_to_each_user(self):
        created = self._create_via_api()
        self.client.patch(f"{self.base_url}{created['short_id']}/", {"is_favorited": True}, format="json")

        other_user = self._create_user("other@posthog.com")
        other_client = APIClient()
        other_client.force_login(other_user)

        response = other_client.get(self.base_url)
        assert response.json()["results"][0]["is_favorited"] is False

    def test_favorited_views_sort_to_top(self):
        older = self._create_via_api(name="Older")
        self._create_via_api(name="Newer")

        # Default order is newest-first; favoriting the older view must float it up
        self.client.patch(f"{self.base_url}{older['short_id']}/", {"is_favorited": True}, format="json")

        results = self.client.get(self.base_url).json()["results"]
        assert [r["name"] for r in results] == ["Older", "Newer"]
        assert results[0]["is_favorited"] is True

    # --- Personal views ---

    @parameterized.expand([("shared_by_default", {}, False), ("explicit_private", {"is_private": True}, True)])
    def test_create_respects_is_private(self, _label, overrides, expected):
        data = self._create_via_api(**overrides)
        assert data["is_private"] is expected
        assert TicketView.objects.get(pk=data["id"]).is_private is expected

    def test_private_view_visible_only_to_creator(self):
        private = self._create_via_api(name="My private view", is_private=True)
        self._create_via_api(name="Team view")

        other_user = self._create_user("other@posthog.com")
        other_client = APIClient()
        other_client.force_login(other_user)

        # Creator sees both their private view and the shared one
        creator_names = {r["name"] for r in self.client.get(self.base_url).json()["results"]}
        assert creator_names == {"My private view", "Team view"}

        # Another user on the team sees only the shared view, and can't fetch the private one directly
        other_names = {r["name"] for r in other_client.get(self.base_url).json()["results"]}
        assert other_names == {"Team view"}
        assert other_client.get(f"{self.base_url}{private['short_id']}/").status_code == status.HTTP_404_NOT_FOUND

        # Flipping it back to shared makes it visible to everyone
        self.client.patch(f"{self.base_url}{private['short_id']}/", {"is_private": False}, format="json")
        assert {r["name"] for r in other_client.get(self.base_url).json()["results"]} == {
            "My private view",
            "Team view",
        }

    def test_personal_view_falls_back_to_shared_once_its_creator_is_gone(self):
        creator = self._create_user("creator@posthog.com")
        orphaned = TicketView.objects.create(
            team=self.team, name="Their personal view", created_by=creator, is_private=True
        )

        def listed():
            return {v["short_id"]: v for v in self.client.get(self.base_url).json()["results"]}

        assert orphaned.short_id not in listed()

        creator.delete()
        orphaned.refresh_from_db()
        assert orphaned.created_by is None

        # With nobody left to keep it for, the view would otherwise be invisible to the
        # whole team and impossible to clean up.
        visible = listed()
        assert orphaned.short_id in visible
        # It also reads as shared, so the list can't badge a team-wide view with a lock
        assert visible[orphaned.short_id]["is_private"] is False

        # ...and nobody can claim it as their own personal view, which could not be honored
        assert (
            self.client.patch(f"{self.base_url}{orphaned.short_id}/", {"is_private": True}, format="json").status_code
            == status.HTTP_400_BAD_REQUEST
        )
        assert (
            self.client.patch(f"{self.base_url}{orphaned.short_id}/", {"is_private": False}, format="json").status_code
            == status.HTTP_200_OK
        )
        orphaned.refresh_from_db()
        assert orphaned.is_private is False

    @parameterized.expand(
        [
            ("visibility_omitted", {"name": "Renamed"}),
            ("visibility_resent_unchanged", {"name": "Renamed", "is_private": False}),
        ]
    )
    def test_editing_a_view_does_not_revert_a_concurrent_visibility_change(self, label, payload):
        created = self._create_via_api(name="Shared team view")

        other_user = self._create_user(f"racer-{label}@posthog.com")
        request = APIRequestFactory().patch("/")
        request.user = other_user

        # What a teammate's in-flight request already loaded, before the creator acted
        stale = TicketView.objects.get(pk=created["id"])
        TicketView.objects.filter(pk=created["id"]).update(is_private=True)

        serializer = TicketViewSerializer(
            stale, data=payload, partial=True, context={"request": request, "team_id": self.team.pk}
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save()

        refreshed = TicketView.objects.get(pk=created["id"])
        assert refreshed.name == "Renamed"
        # The edit must not carry the stale visibility back over the creator's change, whether
        # the teammate omitted the field or resent the value they were shown.
        assert refreshed.is_private is True

    def test_only_creator_can_change_visibility(self):
        created = self._create_via_api(name="Shared team view")

        other_user = self._create_user("other@posthog.com")
        other_client = APIClient()
        other_client.force_login(other_user)

        # Hiding someone else's shared view would strand it: it stays theirs, so the
        # person who hid it can no longer see it to undo the change.
        response = other_client.patch(f"{self.base_url}{created['short_id']}/", {"is_private": True}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert TicketView.objects.get(pk=created["id"]).is_private is False

        # Non-visibility edits by other team members still work on shared views
        assert (
            other_client.patch(f"{self.base_url}{created['short_id']}/", {"name": "Renamed"}, format="json").status_code
            == status.HTTP_200_OK
        )

        # Resending the current visibility isn't a change, so a full-object edit still goes through
        assert (
            other_client.patch(
                f"{self.base_url}{created['short_id']}/",
                {"name": "Renamed again", "is_private": False},
                format="json",
            ).status_code
            == status.HTTP_200_OK
        )

        # ...and the creator can still change it
        assert (
            self.client.patch(f"{self.base_url}{created['short_id']}/", {"is_private": True}, format="json").status_code
            == status.HTTP_200_OK
        )

    # --- Auth ---

    def test_unauthorized_access(self):
        client = APIClient()
        response = client.get(self.base_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
