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

    def test_search_property_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        EnterprisePropertyDefinition.objects.create(
            team=self.team, name="enterprise property", description="", tags=["deprecated"]
        )
        EnterprisePropertyDefinition.objects.create(
            team=self.team, name="other property", description="", tags=["deprecated"]
        )

        response = self.client.get(f"/api/projects/@current/property_definitions/?search=enter")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)

        self.assertEqual(response_data["results"][0]["name"], "enterprise property")
        self.assertEqual(response_data["results"][0]["description"], "")
        self.assertEqual(response_data["results"][0]["tags"], ["deprecated"])

        response = self.client.get(f"/api/projects/@current/property_definitions/?search=enterprise")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)

        response = self.client.get(f"/api/projects/@current/property_definitions/?search=er pr")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 2)

        response = self.client.get(f"/api/projects/@current/property_definitions/?search=bust")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 0)

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
        self.assertIn("This feature is part of the premium PostHog offering.", response.json()["detail"])

    def test_with_expired_license(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2010, 1, 19, 3, 14, 7)
        )
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="description test")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/", data={"description": "test"},
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertIn("This feature is part of the premium PostHog offering.", response.json()["detail"])

    def test_filter_property_definitions(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        EnterprisePropertyDefinition.objects.create(team=self.team, name="plan")
        EnterprisePropertyDefinition.objects.create(team=self.team, name="purchase")
        EnterprisePropertyDefinition.objects.create(team=self.team, name="app_rating")

        response = self.client.get("/api/projects/@current/property_definitions/?properties=plan,app_rating")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.json()["count"], 2)
        for item in response.json()["results"]:
            self.assertIn(item["name"], ["plan", "app_rating"])
