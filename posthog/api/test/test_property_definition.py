import random
from typing import Dict

from rest_framework import status

from posthog.demo import create_demo_team
from posthog.models import EventProperty, Organization, PropertyDefinition, Team
from posthog.tasks.calculate_event_property_usage import calculate_event_property_usage_for_team
from posthog.test.base import APIBaseTest


class TestPropertyDefinitionAPI(APIBaseTest):

    demo_team: Team = None  # type: ignore

    EXPECTED_PROPERTY_DEFINITIONS = [
        {"name": "$browser", "query_usage_30_day": 0, "is_numerical": False},
        {"name": "$current_url", "query_usage_30_day": 0, "is_numerical": False},
        {"name": "is_first_movie", "query_usage_30_day": 0, "is_numerical": False},
        {"name": "app_rating", "query_usage_30_day": 0, "is_numerical": True},
        {"name": "plan", "query_usage_30_day": 0, "is_numerical": False},
        {"name": "purchase", "query_usage_30_day": 0, "is_numerical": True},
        {"name": "purchase_value", "query_usage_30_day": 0, "is_numerical": True},
        {"name": "first_visit", "query_usage_30_day": 0, "is_numerical": False},
    ]

    @classmethod
    def setUpTestData(cls):
        random.seed(900)
        super().setUpTestData()
        cls.demo_team = create_demo_team(cls.organization)
        calculate_event_property_usage_for_team(cls.demo_team.pk)
        cls.user.current_team = cls.demo_team
        cls.user.save()
        EventProperty.objects.create(team=cls.demo_team, event="$pageview", property="$browser")
        EventProperty.objects.create(team=cls.demo_team, event="$pageview", property="first_visit")

    def test_individual_property_formats(self):
        property = PropertyDefinition.objects.create(
            team=self.team, name="timestamp_property", property_type="DateTime",
        )
        response = self.client.get(f"/api/projects/@current/property_definitions/{property.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert response.json()["property_type"] == "DateTime"

    def test_list_property_definitions(self):
        response = self.client.get("/api/projects/@current/property_definitions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), len(self.EXPECTED_PROPERTY_DEFINITIONS))

        self.assertEqual(len(response.json()["results"]), len(self.EXPECTED_PROPERTY_DEFINITIONS))

        for item in self.EXPECTED_PROPERTY_DEFINITIONS:
            response_item: Dict = next((_i for _i in response.json()["results"] if _i["name"] == item["name"]), {})
            self.assertEqual(response_item["query_usage_30_day"], item["query_usage_30_day"])
            self.assertEqual(response_item["is_numerical"], item["is_numerical"])

    def test_list_numerical_property_definitions(self):
        response = self.client.get("/api/projects/@current/property_definitions/?is_numerical=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 3)

        self.assertEqual(len(response.json()["results"]), 3)
        properties = sorted([_i["name"] for _i in response.json()["results"]])

        self.assertEqual(properties, ["app_rating", "purchase", "purchase_value"])

    def test_pagination_of_property_definitions(self):
        PropertyDefinition.objects.bulk_create(
            [PropertyDefinition(team=self.demo_team, name="z_property_{}".format(i)) for i in range(1, 301)]
        )

        response = self.client.get("/api/projects/@current/property_definitions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 100)  # Default page size
        self.assertEqual(response.json()["results"][0]["name"], "$browser")  # Order by name (ascending)

        property_checkpoints = [
            182,
            272,
            92,
        ]  # Because Postgres's sorter does this: property_1; property_100, ..., property_2, property_200, ..., it's
        # easier to deterministically set the expected events

        for i in range(0, 3):
            response = self.client.get(response.json()["next"])
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertEqual(
                len(response.json()["results"]), 100 if i < 2 else 8,
            )  # Each page has 100 except the last one
            self.assertEqual(response.json()["results"][0]["name"], f"z_property_{property_checkpoints[i]}")

    def test_cant_see_property_definitions_for_another_team(self):
        org = Organization.objects.create(name="Separate Org")
        team = Team.objects.create(organization=org, name="Default Project")
        team.event_properties = self.demo_team.event_properties + [f"should_be_invisible_{i}" for i in range(0, 5)]
        team.save()

        response = self.client.get("/api/projects/@current/property_definitions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for item in response.json()["results"]:
            self.assertNotIn("should_be_invisible", item["name"])

        # Also can't fetch for a team to which the user doesn't have permissions
        response = self.client.get(f"/api/projects/{team.pk}/property_definitions/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response())

    def test_query_property_definitions(self):

        # Regular search
        response = self.client.get("/api/projects/@current/property_definitions/?search=firs")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 2)  # first_visit, is_first_movie

        # Fuzzy search
        response = self.client.get("/api/projects/@current/property_definitions/?search=p ting")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["is_event_property"], None)
        for item in response.json()["results"]:
            self.assertIn(item["name"], ["app_rating"])

        # Handles URL encoding properly
        response = self.client.get("/api/projects/@current/property_definitions/?search=%24cur")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        for item in response.json()["results"]:
            self.assertIn(item["name"], ["$current_url"])

        # Shows properties belonging to queried event names
        response = self.client.get(
            "/api/projects/@current/property_definitions/?search=%24&event_names=%5B%22%24pageview%22%5D"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)
        self.assertEqual(response.json()["results"][0]["name"], "$browser")
        self.assertEqual(response.json()["results"][0]["is_event_property"], True)
        self.assertEqual(response.json()["results"][1]["name"], "$current_url")
        self.assertEqual(response.json()["results"][1]["is_event_property"], False)

        # Fuzzy search 2
        response = self.client.get("/api/projects/@current/property_definitions/?search=hase%20")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.json()["results"]), 2)
        for item in response.json()["results"]:
            self.assertIn(item["name"], ["purchase", "purchase_value"])

    def test_is_event_property_filter(self):
        response = self.client.get("/api/projects/@current/property_definitions/?search=firs")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)  # first_visit, is_first_movie

        response = self.client.get(
            "/api/projects/@current/property_definitions/?search=firs&event_names=%5B%22%24pageview%22%5D&is_event_property=true"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["name"], "first_visit")

        response = self.client.get(
            "/api/projects/@current/property_definitions/?search=firs&event_names=%5B%22%24pageview%22%5D&is_event_property=false"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["name"], "is_first_movie")
