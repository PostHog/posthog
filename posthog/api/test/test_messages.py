from rest_framework import status

from posthog.models import HogFunction
from posthog.test.base import APIBaseTest


class TestMessages(APIBaseTest):
    def test_list_messages(self):
        # Create a broadcast message
        broadcast = HogFunction.objects.create(
            team=self.team,
            name="Test Broadcast",
            description="Test Description",
            type="broadcast",
            inputs={"subject": "Test Subject", "body": "Test Body"},
            enabled=True,
        )

        # Create a messaging campaign
        campaign = HogFunction.objects.create(
            team=self.team,
            name="Test Campaign",
            description="Test Campaign Description",
            type="messaging_campaign",
            inputs={"subject": "Campaign Subject", "body": "Campaign Body"},
            enabled=True,
        )

        # Create a function that shouldn't show up
        HogFunction.objects.create(
            team=self.team,
            name="Test Function",
            description="Test Function Description",
            type="destination",
            inputs={"key": "value"},
            enabled=True,
        )

        response = self.client.get(f"/api/messages/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 2)

        # Verify the broadcast message
        broadcast_result = next(r for r in data["results"] if r["id"] == str(broadcast.id))
        self.assertEqual(broadcast_result["name"], "Test Broadcast")
        self.assertEqual(broadcast_result["description"], "Test Description")
        self.assertEqual(broadcast_result["content"], {"subject": "Test Subject", "body": "Test Body"})

        # Verify the campaign message
        campaign_result = next(r for r in data["results"] if r["id"] == str(campaign.id))
        self.assertEqual(campaign_result["name"], "Test Campaign")
        self.assertEqual(campaign_result["description"], "Test Campaign Description")
        self.assertEqual(campaign_result["content"], {"subject": "Campaign Subject", "body": "Campaign Body"})

    def test_retrieve_message(self):
        message = HogFunction.objects.create(
            team=self.team,
            name="Test Message",
            description="Test Description",
            type="broadcast",
            inputs={"subject": "Test Subject", "body": "Test Body"},
            enabled=True,
        )

        response = self.client.get(f"/api/messages/{message.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["name"], "Test Message")
        self.assertEqual(data["description"], "Test Description")
        self.assertEqual(data["content"], {"subject": "Test Subject", "body": "Test Body"})

    def test_cannot_create_message(self):
        response = self.client.post(
            f"/api/messages/",
            {
                "name": "Test Message",
                "description": "Test Description",
                "content": {"subject": "Test Subject", "body": "Test Body"},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_cannot_update_message(self):
        message = HogFunction.objects.create(
            team=self.team,
            name="Test Message",
            description="Test Description",
            type="broadcast",
            inputs={"subject": "Test Subject", "body": "Test Body"},
            enabled=True,
        )

        response = self.client.patch(f"/api/messages/{message.id}/", {"name": "Updated Message"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_cannot_delete_message(self):
        message = HogFunction.objects.create(
            team=self.team,
            name="Test Message",
            description="Test Description",
            type="broadcast",
            inputs={"subject": "Test Subject", "body": "Test Body"},
            enabled=True,
        )

        response = self.client.delete(f"/api/messages/{message.id}/")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
