from typing import cast

import pytest
from django.utils import timezone
from rest_framework import status

from posthog.models import Action
from posthog.models.described_item import EnterpriseDescribedItem
from posthog.test.base import APIBaseTest

# This serializer only tests the business logic of getting and setting of ee descriptions. It uses the action model
# as an example, since model specific functionality is already tested in their models' respective serializer tests.


class TestEnterpriseDescribedItemSerializerMixin(APIBaseTest):
    @pytest.mark.ee
    def test_get_description(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123", plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7), max_users=3,
        )

        action = Action.objects.create(team_id=self.team.id, name="non ee action")
        EnterpriseDescribedItem.objects.create(content_object=action, description="action description", team=self.team)

        response = self.client.get(f"/api/projects/{self.team.id}/actions/{action.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["description"], "action description")

    @pytest.mark.ee
    def test_no_multiple_descriptions_for_same_instance(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123", plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7), max_users=3,
        )

        action = Action.objects.create(team_id=self.team.id, name="non ee action")
        EnterpriseDescribedItem.objects.create(content_object=action, description="action description", team=self.team)

        self.assertEqual(EnterpriseDescribedItem.objects.all().count(), 1)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/actions/{action.id}/", {"name": "Default", "description": "new description"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["description"], "new description")
        self.assertEqual(EnterpriseDescribedItem.objects.all().count(), 1)

    @pytest.mark.ee
    def test_create_and_update_object_with_description(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123", plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7), max_users=3,
        )

        response = self.client.post(f"/api/projects/{self.team.id}/actions/", data={"name": "test action"},)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["description"], None)
        self.assertEqual(EnterpriseDescribedItem.objects.all().count(), 0)

        id = response.json()["id"]
        response = self.client.patch(
            f"/api/projects/{self.team.id}/actions/{id}/", {"name": "test action", "description": "new description"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["description"], "new description")
        self.assertEqual(EnterpriseDescribedItem.objects.all().count(), 1)
