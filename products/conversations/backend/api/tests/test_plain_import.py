from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from rest_framework import status

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_secret

from products.conversations.backend.models import PlainImportJob


class TestPlainImportAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.save(update_fields=["conversations_enabled"])
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.client.force_login(self.user)

    def test_status_returns_404_when_no_job(self):
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/plain_imports/status/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch(
        "products.conversations.backend.api.plain_import.validate_plain_credentials",
        return_value=True,
    )
    @patch(
        "products.conversations.backend.api.plain_import.start_plain_import_workflow",
        new_callable=AsyncMock,
        return_value=("workflow-id", "run-id"),
    )
    def test_start_import_creates_job(self, _mock_start, _mock_validate):
        response = self.client.post(
            f"/api/projects/{self.team.id}/conversations/plain_imports/",
            {
                "api_key": generate_random_token_secret(),
                "region": "uk",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["status"], "running")
        self.assertEqual(response.json()["region"], "uk")
        self.assertTrue(PlainImportJob.objects.unscoped().filter(team_id=self.team.id).exists())

    @patch(
        "products.conversations.backend.api.plain_import.validate_plain_credentials",
        return_value=True,
    )
    @patch(
        "products.conversations.backend.api.plain_import.start_plain_import_workflow",
        new_callable=AsyncMock,
        return_value=("workflow-id", "run-id"),
    )
    def test_start_import_rejects_duplicate_running_job(self, _mock_start, _mock_validate):
        PlainImportJob.objects.unscoped().create(
            team_id=self.team.id,
            status=PlainImportJob.Status.RUNNING,
            job_inputs={"api_key": "x", "region": "uk"},
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/conversations/plain_imports/",
            {
                "api_key": generate_random_token_secret(),
                "region": "us",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_invalid_region(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/conversations/plain_imports/",
            {
                "api_key": generate_random_token_secret(),
                "region": "eu",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_admin_member_cannot_start_or_poll(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        post = self.client.post(
            f"/api/projects/{self.team.id}/conversations/plain_imports/",
            {"api_key": generate_random_token_secret(), "region": "uk"},
            format="json",
        )
        self.assertEqual(post.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(PlainImportJob.objects.unscoped().filter(team_id=self.team.id).exists())

        get = self.client.get(f"/api/projects/{self.team.id}/conversations/plain_imports/status/")
        self.assertEqual(get.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_cannot_target_project_in_another_organization(self):
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other", conversations_enabled=True)

        response = self.client.post(
            f"/api/projects/{other_team.id}/conversations/plain_imports/",
            {"api_key": generate_random_token_secret(), "region": "uk"},
            format="json",
        )
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
