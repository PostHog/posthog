from typing import cast

from django.utils import timezone
from rest_framework import status

from ee.models.license import License, LicenseManager
from ee.models.property_definition import EnterprisePropertyDefinition
from posthog.models.property_definition import PropertyDefinition
from posthog.test.base import APIBaseTest


class TestPropertyDefinitionEnterpriseAPI(APIBaseTest):
    def test_retrieve_existing_property_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        property = EnterprisePropertyDefinition.objects.create(
            team=self.team, name="enterprise property", tags=["deprecated"]
        )
        response = self.client.get(f"/api/projects/@current/property_definitions/{property.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["name"], "enterprise property")
        self.assertEqual(response_data["description"], "")
        self.assertEqual(response_data["tags"], ["deprecated"])

    def test_retrieve_create_property_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        property = PropertyDefinition.objects.create(team=self.team, name="property")
        response = self.client.get(f"/api/projects/@current/property_definitions/{property.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        enterprise_property = EnterprisePropertyDefinition.objects.all().first()
        property.refresh_from_db()
        self.assertEqual(enterprise_property.propertydefinition_ptr_id, property.id)  # type: ignore
        self.assertEqual(enterprise_property.name, property.name)  # type: ignore
        self.assertEqual(enterprise_property.team.id, property.team.id)  # type: ignore

    def test_update_property_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7)
        )
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/",
            {"description": "This is a description.", "tags": ["official", "internal"],},
        )
        response_data = response.json()
        self.assertEqual(response_data["description"], "This is a description.")
        self.assertEqual(response_data["updated_by"]["first_name"], self.user.first_name)
        self.assertEqual(response_data["tags"], ["official", "internal"])

        property.refresh_from_db()
        self.assertEqual(property.tags, ["official", "internal"])

    def test_update_property_without_license(self):
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/", data={"description": "test"},
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(response.json()["detail"], "This is an Enterprise feature.")

    def test_with_expired_license(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2010, 1, 19, 3, 14, 7)
        )
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="description test")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/", data={"description": "test"},
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(response.json()["detail"], "This is an Enterprise feature.")
