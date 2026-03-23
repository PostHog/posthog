"""Tests for ticket person enrichment via the personhog path.

Mirrors the person-related tests from test_tickets.py to ensure the
personhog code path returns identical results to the ORM path.
"""

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import transaction

from rest_framework import status

from posthog.personhog_client.fake_client import fake_personhog_client

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Status


def immediate_on_commit(func):
    func()


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestTicketsPersonhog(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="test-session-123",
            distinct_id="user-123",
            status=Status.NEW,
        )

    def test_list_tickets_includes_person_data_via_personhog(self, mock_on_commit):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=self.team.pk,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440000",
                distinct_ids=["user-123", "user@example.com"],
                properties={"email": "test@example.com"},
            )

            response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")

            assert response.status_code == status.HTTP_200_OK
            assert response.json()["count"] == 1
            person = response.json()["results"][0]["person"]
            assert person is not None
            assert person["properties"]["email"] == "test@example.com"
            assert set(person["distinct_ids"]) == {"user-123", "user@example.com"}
            fake.assert_called("get_persons_by_distinct_ids_in_team")

    def test_retrieve_ticket_includes_person_data_via_personhog(self, mock_on_commit):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=self.team.pk,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440000",
                distinct_ids=["user-123", "alt-id"],
                properties={"email": "test@example.com", "name": "Test User"},
            )

            response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")

            assert response.status_code == status.HTTP_200_OK
            person = response.json()["person"]
            assert person is not None
            assert person["id"] == "550e8400-e29b-41d4-a716-446655440000"
            assert person["properties"]["name"] == "Test User"
            assert set(person["distinct_ids"]) == {"user-123", "alt-id"}
            fake.assert_called("get_persons_by_distinct_ids_in_team")

    def test_person_null_when_not_found_via_personhog(self, mock_on_commit):
        with fake_personhog_client():
            response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")

            assert response.status_code == status.HTTP_200_OK
            assert response.json()["person"] is None

    def test_cross_team_isolation_via_personhog(self, mock_on_commit):
        other_team = self.organization.teams.create(name="Other Team")

        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=other_team.pk,
                person_id=42,
                uuid="550e8400-e29b-41d4-a716-446655440000",
                distinct_ids=["user-123"],
                properties={"email": "other@example.com"},
            )

            response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")

            assert response.status_code == status.HTTP_200_OK
            assert response.json()["person"] is None
