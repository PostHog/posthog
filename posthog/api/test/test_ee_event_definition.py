import random

from rest_framework import status

from posthog.demo import create_demo_team
from posthog.models import Organization, Team
from posthog.tasks.calculate_event_property_usage import calculate_event_property_usage_for_team
from posthog.test.base import APIBaseTest


class TestEEEventDefinitionAPI(APIBaseTest):

    demo_team: Team = None  # type: ignore

    @classmethod
    def setUpTestData(cls):
        random.seed(900)
        super().setUpTestData()
        org = Organization.objects.create(name="Enterprise Org", available_features=["ingestion_taxonomy"])
        cls.demo_team = create_demo_team(org)
        calculate_event_property_usage_for_team(cls.demo_team.pk)
        cls.user.current_organization = org
        cls.user.current_team = cls.demo_team
        cls.user.save()

    def test_query_ee_event_definitions(self):

        # Fuzzy search works
        response = self.client.get("/api/projects/@current/event_definitions/?search=free trl")
        print(response.json())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.json()["count"], 1)
        for item in response.json()["results"]:
            self.assertIn(item["name"], ["entered_free_trial"])
