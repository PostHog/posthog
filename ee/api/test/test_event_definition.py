from typing import cast

from django.utils import timezone
from rest_framework import status

from ee.models.event_definition import EnterpriseEventDefinition
from ee.models.license import License, LicenseManager
from posthog.test.base import APIBaseTest


class TestEventDefinitionEnterpriseAPI(APIBaseTest):
    def test_event_description(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7)
        )
        event = EnterpriseEventDefinition.objects.create(team=self.team, name="description test")
        response = self.client.patch(
            f"/api/projects/@current/event_definitions/{str(event.id)}/",
            data={"description": "This is a description."},
        )
        self.assertEqual(response.json()["description"], "This is a description.")

    def test_for_license(self):
        event = EnterpriseEventDefinition.objects.create(team=self.demo_team, name="description test")
        response = self.client.get(
            f"/api/projects/@current/event_definitions/{str(event.id)}/", data={"description": "test"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["detail"], "This is an Enterprise plan feature.")
