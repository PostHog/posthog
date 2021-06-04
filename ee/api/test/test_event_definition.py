from typing import cast

from django.utils import timezone
from rest_framework import status

from ee.models.event_definition import EnterpriseEventDefinition
from ee.models.license import License, LicenseManager
from posthog.models import team
from posthog.models.event_definition import EventDefinition
from posthog.test.base import APIBaseTest


class TestEventDefinitionEnterpriseAPI(APIBaseTest):
    def test_retrieve_existing_event_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        event = EnterpriseEventDefinition.objects.create(
            team=self.team, name="enterprise event", owner=self.user, tags=["deprecated"]
        )
        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["name"], "enterprise event")
        self.assertEqual(response_data["description"], "")
        self.assertEqual(response_data["tags"], ["deprecated"])
        self.assertEqual(response_data["owner"]["distinct_id"], self.user.distinct_id)
        self.assertEqual(response_data["owner"]["first_name"], self.user.first_name)

    def test_retrieve_create_event_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        event = EventDefinition.objects.create(team=self.team, name="event")
        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        enterprise_event = EnterpriseEventDefinition.objects.all().first()
        event.refresh_from_db()
        self.assertEqual(enterprise_event.eventdefinition_ptr_id, event.id)  # type: ignore
        self.assertEqual(enterprise_event.name, event.name)  # type: ignore
        self.assertEqual(enterprise_event.team.id, event.team.id)  # type: ignore

    def test_update_event_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7)
        )
        event = EnterpriseEventDefinition.objects.create(team=self.team, name="enterprise event", owner=self.user)
        response = self.client.patch(
            f"/api/projects/@current/event_definitions/{str(event.id)}/",
            {"description": "This is a description.", "tags": ["official", "internal"],},
        )
        response_data = response.json()
        self.assertEqual(response_data["description"], "This is a description.")
        self.assertEqual(response_data["updated_by"]["first_name"], self.user.first_name)
        self.assertEqual(response_data["tags"], ["official", "internal"])

        event.refresh_from_db()
        self.assertEqual(event.description, "This is a description.")
        self.assertEqual(event.tags, ["official", "internal"])

    def test_update_event_without_license(self):
        event = EnterpriseEventDefinition.objects.create(team=self.team, name="enterprise event")
        response = self.client.patch(
            f"/api/projects/@current/event_definitions/{str(event.id)}/", data={"description": "test"},
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(response.json()["detail"], "This is an Enterprise feature.")

    def test_with_expired_license(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2010, 1, 19, 3, 14, 7)
        )
        event = EnterpriseEventDefinition.objects.create(team=self.team, name="description test")
        response = self.client.patch(
            f"/api/projects/@current/event_definitions/{str(event.id)}/", data={"description": "test"},
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(response.json()["detail"], "This is an Enterprise feature.")
