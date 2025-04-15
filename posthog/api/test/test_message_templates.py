from rest_framework import status

from posthog.models import HogFunction, Team, Organization
from posthog.test.base import APIBaseTest
import json


class TestMessageTemplatesAPI(APIBaseTest):
    def setUp(self):
        super().setUp()

        self.message_template = HogFunction.objects.create(
            team=self.team,
            name="Test Template",
            description="Test description",
            hog="Test hog content",
            kind="messaging_template",
            inputs={"email_template": {"subject": "Test Subject", "body": "Test Body"}},
            inputs_schema=[{"type": "email_template", "key": "email_template"}],
        )

        self.other_function = HogFunction.objects.create(
            team=self.team,
            name="Not a Template",
            description="Not a template description",
            hog="Test hog content",
            kind="something_else",
            inputs={"email_template": {"subject": "Should not show", "body": "Should not show"}},
            inputs_schema=[{"type": "email_template", "key": "email_template"}],
        )

        self.other_org = Organization.objects.create(name="Other Org")
        self.other_team = Team.objects.create(organization=self.other_org, name="Other Team")
        self.other_team_template = HogFunction.objects.create(
            team=self.other_team,
            name="Other Team Template",
            description="Other team template description",
            hog="Test hog content",
            kind="messaging_template",
            inputs={"email_template": {"subject": "Other Team Subject", "body": "Other Team Body"}},
            inputs_schema=[{"type": "email_template", "key": "email_template"}],
        )

    def test_list_message_templates(self):
        response = self.client.get(f"/api/environments/{self.team.id}/messaging/templates/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)

        template = response_data["results"][0]
        self.assertEqual(template["id"], str(self.message_template.id))
        self.assertEqual(template["name"], "Test Template")
        self.assertEqual(template["description"], "Test description")
        self.assertEqual(template["kind"], "messaging_template")
        self.assertEqual(template["content"], {"subject": "Test Subject", "body": "Test Body"})

    def test_retrieve_message_template(self):
        response = self.client.get(f"/api/environments/{self.team.id}/messaging/templates/{self.message_template.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        template = response.json()
        self.assertEqual(template["id"], str(self.message_template.id))
        self.assertEqual(template["name"], "Test Template")
        self.assertEqual(template["description"], "Test description")
        self.assertEqual(template["kind"], "messaging_template")
        self.assertEqual(template["content"], {"subject": "Test Subject", "body": "Test Body"})

    def test_cannot_retrieve_non_template(self):
        response = self.client.get(f"/api/environments/{self.team.id}/messaging/templates/{self.other_function.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_access_other_teams_templates(self):
        response = self.client.get(f"/api/environments/{self.other_team.id}/messaging/templates/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.get(
            f"/api/environments/{self.team.id}/messaging/templates/{self.other_team_template.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_authentication_required(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/messaging/templates/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_write_operations_not_allowed(self):
        post_data = {
            "name": "New Template",
            "description": "New template description",
            "hog": "New hog content",
            "kind": "messaging_template",
            "inputs": {"email_template": {"subject": "New Subject", "body": "New Body"}},
        }
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging/templates/",
            data=json.dumps(post_data),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        put_data = {
            "name": "Updated Template",
            "description": "Updated template description",
            "hog": "Updated hog content",
            "kind": "messaging_template",
            "inputs": {"email_template": {"subject": "Updated Subject", "body": "Updated Body"}},
        }
        response = self.client.put(
            f"/api/environments/{self.team.id}/messaging/templates/{self.message_template.id}/",
            data=json.dumps(put_data),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        patch_data = {
            "name": "Patched Template",
        }
        response = self.client.patch(
            f"/api/environments/{self.team.id}/messaging/templates/{self.message_template.id}/",
            data=json.dumps(patch_data),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/messaging/templates/{self.message_template.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        response = self.client.get(f"/api/environments/{self.team.id}/messaging/templates/{self.message_template.id}/")
        template = response.json()
        self.assertEqual(template["name"], "Test Template")  # Name still the same, not updated
