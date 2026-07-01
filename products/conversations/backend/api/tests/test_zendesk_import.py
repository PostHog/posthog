from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from rest_framework import status

from posthog.models.organization import OrganizationMembership
from posthog.models.utils import generate_random_token_secret

from products.conversations.backend.models import ZendeskImportJob


class TestZendeskImportAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.save(update_fields=["conversations_enabled"])
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.client.force_login(self.user)

    def test_status_returns_404_when_no_job(self):
        response = self.client.get("/api/conversations/v1/zendesk/import/status")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch(
        "products.conversations.backend.api.zendesk_import.validate_zendesk_credentials",
        return_value=True,
    )
    @patch(
        "products.conversations.backend.api.zendesk_import.start_zendesk_import_workflow",
        new_callable=AsyncMock,
        return_value=("workflow-id", "run-id"),
    )
    def test_start_import_creates_job(self, _mock_start, _mock_validate):
        response = self.client.post(
            "/api/conversations/v1/zendesk/import",
            {
                "subdomain": "acme",
                "email_address": "agent@example.com",
                "api_token": generate_random_token_secret(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["status"], "running")
        self.assertTrue(ZendeskImportJob.objects.unscoped().filter(team_id=self.team.id).exists())

    @patch(
        "products.conversations.backend.api.zendesk_import.validate_zendesk_credentials",
        return_value=True,
    )
    @patch(
        "products.conversations.backend.api.zendesk_import.start_zendesk_import_workflow",
        new_callable=AsyncMock,
        return_value=("workflow-id", "run-id"),
    )
    def test_start_import_rejects_duplicate_running_job(self, _mock_start, _mock_validate):
        ZendeskImportJob.objects.unscoped().create(
            team_id=self.team.id,
            status=ZendeskImportJob.Status.RUNNING,
            job_inputs={"subdomain": "acme", "email_address": "a@b.com", "api_token": "x"},
        )
        response = self.client.post(
            "/api/conversations/v1/zendesk/import",
            {
                "subdomain": "acme",
                "email_address": "agent@example.com",
                "api_token": generate_random_token_secret(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
