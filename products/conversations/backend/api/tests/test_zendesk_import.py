from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from rest_framework import status

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team
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
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/zendesk_imports/status/")
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
            f"/api/projects/{self.team.id}/conversations/zendesk_imports/",
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
            f"/api/projects/{self.team.id}/conversations/zendesk_imports/",
            {
                "subdomain": "acme",
                "email_address": "agent@example.com",
                "api_token": generate_random_token_secret(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_admin_member_cannot_start_or_poll(self):
        # A plain member of the routed team must not be able to start an import or read status —
        # the endpoint requires org-admin, not just team membership.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        post = self.client.post(
            f"/api/projects/{self.team.id}/conversations/zendesk_imports/",
            {"subdomain": "acme", "email_address": "agent@example.com", "api_token": generate_random_token_secret()},
            format="json",
        )
        self.assertEqual(post.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(ZendeskImportJob.objects.unscoped().filter(team_id=self.team.id).exists())

        get = self.client.get(f"/api/projects/{self.team.id}/conversations/zendesk_imports/status/")
        self.assertEqual(get.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_cannot_target_project_in_another_organization(self):
        # Being an admin of one org must not authorize importing into a project the user
        # has no membership in — the gate is scoped to the routed team, not org-wide.
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other", conversations_enabled=True)

        response = self.client.post(
            f"/api/projects/{other_team.id}/conversations/zendesk_imports/",
            {"subdomain": "acme", "email_address": "agent@example.com", "api_token": generate_random_token_secret()},
            format="json",
        )
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
        self.assertFalse(ZendeskImportJob.objects.unscoped().filter(team_id=other_team.id).exists())
