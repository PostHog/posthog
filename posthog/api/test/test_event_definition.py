import random
from typing import Dict

from rest_framework import status

from posthog.demo import create_demo_team
from posthog.models import EventDefinition, Organization, Team
from posthog.tasks.calculate_event_property_usage import calculate_event_property_usage_for_team
from posthog.test.base import APIBaseTest


class TestEventDefinitionAPI(APIBaseTest):

    demo_team: Team = None  # type: ignore

    EXPECTED_EVENT_DEFINITIONS = [
        {"name": "installed_app", "volume_30_day": 100, "query_usage_30_day": 0},
        {"name": "rated_app", "volume_30_day": 73, "query_usage_30_day": 0},
        {"name": "purchase", "volume_30_day": 16, "query_usage_30_day": 0},
        {"name": "entered_free_trial", "volume_30_day": 0, "query_usage_30_day": 0},
        {"name": "watched_movie", "volume_30_day": 87, "query_usage_30_day": 0},
        {"name": "$pageview", "volume_30_day": 327, "query_usage_30_day": 0},
    ]

    @classmethod
    def setUpTestData(cls):
        random.seed(900)
        super().setUpTestData()
        cls.demo_team = create_demo_team(cls.organization)
        calculate_event_property_usage_for_team(cls.demo_team.pk)
        cls.user.current_team = cls.demo_team
        cls.user.save()

    def test_list_event_definitions(self):

        response = self.client.get("/api/projects/@current/event_definitions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], len(self.EXPECTED_EVENT_DEFINITIONS))
        self.assertEqual(len(response.json()["results"]), len(self.EXPECTED_EVENT_DEFINITIONS))

        for item in self.EXPECTED_EVENT_DEFINITIONS:
            response_item: Dict = next((_i for _i in response.json()["results"] if _i["name"] == item["name"]), {})
            self.assertEqual(response_item["volume_30_day"], item["volume_30_day"], item)
            self.assertEqual(response_item["query_usage_30_day"], item["query_usage_30_day"], item)
            self.assertEqual(
                response_item["volume_30_day"], EventDefinition.objects.get(id=response_item["id"]).volume_30_day, item,
            )

    def test_pagination_of_event_definitions(self):
        EventDefinition.objects.bulk_create(
            [EventDefinition(team=self.demo_team, name="z_event_{}".format(i)) for i in range(1, 301)]
        )

        response = self.client.get("/api/projects/@current/event_definitions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 306)
        self.assertEqual(len(response.json()["results"]), 100)  # Default page size
        self.assertEqual(response.json()["results"][0]["name"], "$pageview")  # Order by name (ascending)
        self.assertEqual(response.json()["results"][1]["name"], "entered_free_trial")  # Order by name (ascending)

        event_checkpoints = [
            184,
            274,
            94,
        ]  # Because Postgres's sorter does this: event_1; event_100, ..., event_2, event_200, ..., it's
        # easier to deterministically set the expected events

        for i in range(0, 3):
            response = self.client.get(response.json()["next"])
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertEqual(response.json()["count"], 306)
            self.assertEqual(
                len(response.json()["results"]), 100 if i < 2 else 6,
            )  # Each page has 100 except the last one
            self.assertEqual(response.json()["results"][0]["name"], f"z_event_{event_checkpoints[i]}")

    def test_cant_see_event_definitions_for_another_team(self):
        org = Organization.objects.create(name="Separate Org")
        team = Team.objects.create(organization=org, name="Default Project")

        EventDefinition.objects.create(team=team, name="should_be_invisible")

        response = self.client.get("/api/projects/@current/event_definitions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for item in response.json()["results"]:
            self.assertNotIn("should_be_invisible", item["name"])

        # Also can't fetch for a team to which the user doesn't have permissions
        response = self.client.get(f"/api/projects/{team.pk}/event_definitions/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response())

    def test_query_event_definitions(self):

        # Regular search
        response = self.client.get("/api/projects/@current/event_definitions/?search=app")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)  # rated app, installed app

        # Fuzzy search 1
        response = self.client.get("/api/projects/@current/event_definitions/?search=free tri")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        for item in response.json()["results"]:
            self.assertIn(item["name"], ["entered_free_trial"])

        # Handles URL encoding properly
        response = self.client.get("/api/projects/@current/event_definitions/?search=free%20tri%20")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        for item in response.json()["results"]:
            self.assertIn(item["name"], ["entered_free_trial"])

        # Fuzzy search 2
        response = self.client.get("/api/projects/@current/event_definitions/?search=ed mov")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        for item in response.json()["results"]:
            self.assertIn(item["name"], ["watched_movie"])
