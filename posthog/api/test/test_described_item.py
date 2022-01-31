from rest_framework import status

from posthog.models import Action
from posthog.models.described_item import EnterpriseDescribedItem
from posthog.test.base import APIBaseTest

# This serializer only tests that enterprise functionality is not exposed on non-ee requests. It uses the action model
# as an example, since model specific functionality is already tested in their models' respective serializer tests.


class TestDescribedItemSerializerMixin(APIBaseTest):
    def test_get_description_on_non_ee_returns_null(self):
        action = Action.objects.create(team_id=self.team.id, name="non ee action")
        EnterpriseDescribedItem.objects.create(content_object=action, description="action description", team=self.team)

        response = self.client.get(f"/api/projects/{self.team.id}/actions/{action.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["description"], None)
        self.assertEqual(EnterpriseDescribedItem.objects.all().count(), 1)

    def test_create_description_on_non_ee_not_allowed(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/actions/", data={"name": "test action", "description": "action description"},
        )

        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)

    def test_update_description_on_non_ee_not_allowed(self):
        action = Action.objects.create(team_id=self.team.id, name="non ee action")
        EnterpriseDescribedItem.objects.create(content_object=action, description="action description", team=self.team)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/actions/{action.id}/",
            {"name": "action new name", "description": "new description",},
        )

        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(EnterpriseDescribedItem.objects.all().count(), 1)

    def test_empty_description_does_not_delete_description(self):
        action = Action.objects.create(team_id=self.team.id, name="non ee action")
        EnterpriseDescribedItem.objects.create(content_object=action, description="action description", team=self.team)

        self.assertEqual(EnterpriseDescribedItem.objects.all().count(), 1)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/actions/{action.id}/", {"name": "action new name", "description": ""},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "action new name")
        self.assertEqual(EnterpriseDescribedItem.objects.all().count(), 1)
