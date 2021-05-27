from typing import cast

from django.utils import timezone
from ee.models.license import License, LicenseManager
from rest_framework import status
from posthog.test.base import APIBaseTest
from posthog.models.property_definition import PropertyDefinition

class TestPropertyDefinitionEnterpriseAPI(APIBaseTest):

    def test_property_description(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7))
        property = PropertyDefinition.objects.create(team=self.demo_team, name="description test")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{property.id}/",
            data={
                "description": "test"
            },
        )
        self.assertEqual(response.json()["description"], "test")


    def test_for_license(self):
        property = PropertyDefinition.objects.create(team=self.demo_team, name="description test")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{property.id}/",
            data={
                "description": "test"
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["detail"], "Enterprise plan feature")