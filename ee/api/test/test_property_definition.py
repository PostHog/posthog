from typing import cast

from django.utils import timezone
from rest_framework import status

from ee.models.license import License, LicenseManager
from ee.models.property_definition import EnterprisePropertyDefinition
from posthog.test.base import APIBaseTest


class TestPropertyDefinitionEnterpriseAPI(APIBaseTest):
    def test_property_description(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7)
        )
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="description test")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/",
            data={"description": "This is a description."},
        )
        self.assertEqual(response.json()["description"], "This is a description.")

    def test_for_license(self):
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="description test")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/", data={"description": "test"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["detail"], "This is an Enterprise plan feature.")
