from rest_framework import status

from posthog.models import MessageTemplate, Team, Organization
from posthog.test.base import APIBaseTest


class TestMessageTemplatesAPI(APIBaseTest):
    def setUp(self):
        super().setUp()

        self.message_template = MessageTemplate.objects.create(
            team=self.team,
            name="Test Template",
            description="Test description",
            content={"subject": "Test Subject", "body": "Test Body"},
            type="email",
        )

        self.other_org = Organization.objects.create(name="Other Org")
        self.other_team = Team.objects.create(organization=self.other_org, name="Other Team")
        self.other_team_template = MessageTemplate.objects.create(
            team=self.other_team,
            name="Other Team Template",
            description="Other team template description",
            content={"subject": "Other Team Subject", "body": "Other Team Body"},
            type="email",
        )

    def test_list_message_templates(self):
        response = self.client.get(f"/api/environments/{self.team.id}/messaging_templates/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)

        template = response_data["results"][0]
        self.assertEqual(template["id"], str(self.message_template.id))
        self.assertEqual(template["name"], "Test Template")
        self.assertEqual(template["description"], "Test description")
        self.assertEqual(template["content"], {"subject": "Test Subject", "body": "Test Body"})
        self.assertEqual(template["type"], "email")

    def test_retrieve_message_template(self):
        response = self.client.get(f"/api/environments/{self.team.id}/messaging_templates/{self.message_template.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        template = response.json()
        self.assertEqual(template["id"], str(self.message_template.id))
        self.assertEqual(template["name"], "Test Template")
        self.assertEqual(template["description"], "Test description")
        self.assertEqual(template["content"], {"subject": "Test Subject", "body": "Test Body"})
        self.assertEqual(template["type"], "email")

    def test_cannot_access_other_teams_templates(self):
        response = self.client.get(f"/api/environments/{self.other_team.id}/messaging_templates/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.get(
            f"/api/environments/{self.team.id}/messaging_templates/{self.other_team_template.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_authentication_required(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/messaging_templates/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_delete_operation_not_allowed(self):
        response = self.client.delete(
            f"/api/environments/{self.team.id}/messaging_templates/{self.message_template.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
