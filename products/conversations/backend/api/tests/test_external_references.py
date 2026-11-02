from unittest.mock import Mock, patch
from uuid import uuid4

from rest_framework import status

from posthog.models import Integration
from posthog.test.base import APIBaseTest

from products.conversations.backend.models import Ticket, TicketExternalReference


class TestTicketExternalReferencesAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create(
            team=self.team,
            ticket_number=42,
            distinct_id="user_123",
            channel_source="email",
            email_subject="Cannot access dashboard",
        )
        self.integration = Integration.objects.create(
            team=self.team,
            kind="github",
            config={"account": {"name": "test-org"}},
        )

    def test_list_external_references_empty(self):
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/external_references/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    @patch("products.conversations.backend.logic.external_references.GitHubIntegration")
    def test_create_external_reference_creates_github_issue(self, mock_github_class):
        mock_github = Mock()
        mock_github.create_issue.return_value = {
            "repository": "test-repo",
            "number": 101,
            "title": "Bug: Cannot access dashboard",
            "url": "https://github.com/test-org/test-repo/issues/101",
        }
        mock_github_class.return_value = mock_github

        response = self.client.post(
            f"/api/projects/{self.team.id}/conversations/external_references/",
            {
                "ticket": str(self.ticket.id),
                "integration_id": self.integration.id,
                "config": {
                    "repository": "test-repo",
                    "title": "Bug: Cannot access dashboard",
                    "body": "User reported 403 on dashboard.",
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["ticket_id"] == str(self.ticket.id)
        assert data["title"] == "Bug: Cannot access dashboard"
        assert data["external_id"] == "101"
        assert "101" in data["external_url"]

        # Verify backlink was appended to body
        call_config = mock_github.create_issue.call_args[0][0]
        assert "PostHog Support Ticket #42" in call_config["body"]

        # Verify stored in DB
        assert TicketExternalReference.objects.filter(ticket=self.ticket).count() == 1

    def test_link_existing_issue(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/conversations/external_references/link_issue/",
            {
                "ticket": str(self.ticket.id),
                "integration_id": self.integration.id,
                "external_context": {
                    "repository": "test-repo",
                    "number": 202,
                    "title": "Fix dashboard 403 error",
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["title"] == "Fix dashboard 403 error"
        assert data["external_id"] == "202"
        assert "202" in data["external_url"]

        # Idempotent re-link
        response2 = self.client.post(
            f"/api/projects/{self.team.id}/conversations/external_references/link_issue/",
            {
                "ticket": str(self.ticket.id),
                "integration_id": self.integration.id,
                "external_context": {
                    "repository": "test-repo",
                    "number": 202,
                    "title": "Fix dashboard 403 error (updated title)",
                },
            },
        )
        assert response2.status_code == status.HTTP_201_CREATED
        assert TicketExternalReference.objects.filter(ticket=self.ticket).count() == 1

    def test_destroy_external_reference(self):
        ref = TicketExternalReference.objects.create(
            ticket=self.ticket,
            integration=self.integration,
            external_context={"repository": "test-repo", "number": 303, "title": "Old bug"},
        )

        response = self.client.delete(
            f"/api/projects/{self.team.id}/conversations/external_references/{ref.id}/"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not TicketExternalReference.objects.filter(id=ref.id).exists()

    def test_destroy_nonexistent_reference_returns_404(self):
        response = self.client.delete(
            f"/api/projects/{self.team.id}/conversations/external_references/{uuid4()}/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("products.conversations.backend.logic.external_references.GitHubIntegration")
    def test_search_issues(self, mock_github_class):
        mock_github = Mock()
        mock_github.search_issues.return_value = [
            {
                "id": "101",
                "title": "Bug in dashboard",
                "url": "https://github.com/test-org/test-repo/issues/101",
                "external_context": {"repository": "test-repo", "number": 101, "title": "Bug in dashboard"},
            }
        ]
        mock_github_class.return_value = mock_github

        response = self.client.get(
            f"/api/projects/{self.team.id}/conversations/external_references/search_issues/",
            {
                "integration_id": self.integration.id,
                "repository": "test-repo",
                "search": "dashboard",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["issues"]) == 1
        assert data["issues"][0]["title"] == "Bug in dashboard"

    def test_ticket_detail_includes_external_references(self):
        TicketExternalReference.objects.create(
            ticket=self.ticket,
            integration=self.integration,
            external_context={"repository": "test-repo", "number": 404, "title": "Dashboard fix"},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "external_references" in data
        assert len(data["external_references"]) == 1
        assert data["external_references"][0]["title"] == "Dashboard fix"
        assert data["external_references"][0]["external_id"] == "404"
