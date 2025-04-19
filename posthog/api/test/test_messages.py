from rest_framework import status

from posthog.models import HogFunction, Team, Organization
from posthog.test.base import APIBaseTest
import json


class TestMessagesAPI(APIBaseTest):
    def setUp(self):
        super().setUp()

        self.broadcast_message = HogFunction.objects.create(
            team=self.team,
            name="Test Broadcast",
            description="Test broadcast description",
            hog="Test hog content",
            type="broadcast",
            inputs={"email": {"subject": "Broadcast Subject", "body": "Broadcast Body"}},
            inputs_schema=[{"type": "email", "key": "email"}],
        )

        self.campaign_message = HogFunction.objects.create(
            team=self.team,
            name="Test Campaign",
            description="Test campaign description",
            hog="Test hog content",
            kind="messaging_campaign",
            inputs={"email": {"subject": "Campaign Subject", "body": "Campaign Body"}},
            inputs_schema=[{"type": "email", "key": "email"}],
        )

        self.other_function = HogFunction.objects.create(
            team=self.team,
            name="Not a Message",
            description="Not a message description",
            hog="Test hog content",
            type="something_else",
            kind="something_else",
            inputs={"email": {"subject": "Should not show", "body": "Should not show"}},
            inputs_schema=[{"type": "email", "key": "email"}],
        )

        self.other_org = Organization.objects.create(name="Other Org")
        self.other_team = Team.objects.create(organization=self.other_org, name="Other Team")
        self.other_team_message = HogFunction.objects.create(
            team=self.other_team,
            name="Other Team Message",
            description="Other team message description",
            hog="Test hog content",
            type="broadcast",
            inputs={"email": {"subject": "Other Team Subject", "body": "Other Team Body"}},
            inputs_schema=[{"type": "email", "key": "email"}],
        )

    def test_list_messages(self):
        response = self.client.get(f"/api/environments/{self.team.id}/messaging/messages/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 2)

        results = sorted(response_data["results"], key=lambda x: x["name"])

        # Verify first message (broadcast)
        self.assertEqual(results[0]["id"], str(self.broadcast_message.id))
        self.assertEqual(results[0]["name"], "Test Broadcast")
        self.assertEqual(results[0]["description"], "Test broadcast description")
        self.assertEqual(results[0]["type"], "broadcast")
        self.assertEqual(results[0]["content"], {"subject": "Broadcast Subject", "body": "Broadcast Body"})

        # Verify second message (campaign)
        self.assertEqual(results[1]["id"], str(self.campaign_message.id))
        self.assertEqual(results[1]["name"], "Test Campaign")
        self.assertEqual(results[1]["description"], "Test campaign description")
        self.assertEqual(results[1]["kind"], "messaging_campaign")
        self.assertEqual(results[1]["content"], {"subject": "Campaign Subject", "body": "Campaign Body"})

    def test_retrieve_broadcast_message(self):
        response = self.client.get(f"/api/environments/{self.team.id}/messaging/messages/{self.broadcast_message.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        message = response.json()
        self.assertEqual(message["id"], str(self.broadcast_message.id))
        self.assertEqual(message["name"], "Test Broadcast")
        self.assertEqual(message["description"], "Test broadcast description")
        self.assertEqual(message["type"], "broadcast")
        self.assertEqual(message["content"], {"subject": "Broadcast Subject", "body": "Broadcast Body"})

    def test_retrieve_campaign_message(self):
        response = self.client.get(f"/api/environments/{self.team.id}/messaging/messages/{self.campaign_message.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        message = response.json()
        self.assertEqual(message["id"], str(self.campaign_message.id))
        self.assertEqual(message["name"], "Test Campaign")
        self.assertEqual(message["description"], "Test campaign description")
        self.assertEqual(message["kind"], "messaging_campaign")
        self.assertEqual(message["content"], {"subject": "Campaign Subject", "body": "Campaign Body"})

    def test_cannot_retrieve_non_message(self):
        response = self.client.get(f"/api/environments/{self.team.id}/messaging/messages/{self.other_function.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_access_other_teams_messages(self):
        # Try to list the other team's messages
        response = self.client.get(f"/api/environments/{self.other_team.id}/messaging/messages/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Try to retrieve the other team's message
        response = self.client.get(f"/api/environments/{self.team.id}/messaging/messages/{self.other_team_message.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_authentication_required(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/messaging/messages/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_write_operations_not_allowed(self):
        post_data = {
            "name": "New Message",
            "description": "New message description",
            "hog": "New hog content",
            "type": "broadcast",
            "inputs": {"email": {"subject": "New Subject", "body": "New Body"}},
        }
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging/messages/",
            data=json.dumps(post_data),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        put_data = {
            "name": "Updated Message",
            "description": "Updated message description",
            "hog": "Updated hog content",
            "type": "broadcast",
            "inputs": {"email": {"subject": "Updated Subject", "body": "Updated Body"}},
        }
        response = self.client.put(
            f"/api/environments/{self.team.id}/messaging/messages/{self.broadcast_message.id}/",
            data=json.dumps(put_data),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        patch_data = {
            "name": "Patched Message",
        }
        response = self.client.patch(
            f"/api/environments/{self.team.id}/messaging/messages/{self.broadcast_message.id}/",
            data=json.dumps(patch_data),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/messaging/messages/{self.broadcast_message.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        response = self.client.get(f"/api/environments/{self.team.id}/messaging/messages/{self.broadcast_message.id}/")
        message = response.json()
        self.assertEqual(message["name"], "Test Broadcast")  # Name still the same, not updated
