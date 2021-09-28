import dataclasses
from datetime import datetime
from typing import Any, Dict, List, cast
from uuid import uuid4

from django.conf import settings
from freezegun.api import freeze_time
from rest_framework import status

from posthog.models import Event, EventDefinition, Organization, Team
from posthog.models.user import User
from posthog.tasks.calculate_event_property_usage import calculate_event_property_usage_for_team
from posthog.test.base import APIBaseTest


@freeze_time("2020-01-02")
class TestEventDefinitionAPI(APIBaseTest):

    demo_team: Team = None  # type: ignore

    EXPECTED_EVENT_DEFINITIONS: List[Dict[str, Any]] = [
        {"name": "installed_app", "volume_30_day": 1, "query_usage_30_day": 0},
        {"name": "rated_app", "volume_30_day": 2, "query_usage_30_day": 0},
        {"name": "purchase", "volume_30_day": 3, "query_usage_30_day": 0},
        {"name": "entered_free_trial", "volume_30_day": 7, "query_usage_30_day": 0},
        {"name": "watched_movie", "volume_30_day": 8, "query_usage_30_day": 0},
        {"name": "$pageview", "volume_30_day": 9, "query_usage_30_day": 0},
    ]

    @classmethod
    def setUpTestData(cls):
        cls.organization = create_organization(name="test org")
        cls.demo_team = create_team(organization=cls.organization)
        cls.user = create_user("user", "pass", cls.organization)

        for event_definition in cls.EXPECTED_EVENT_DEFINITIONS:
            create_event_definitions(event_definition["name"], team_id=cls.demo_team.pk)
            for _ in range(event_definition["volume_30_day"]):
                capture_event(
                    event=EventData(
                        event=event_definition["name"],
                        team_id=cls.demo_team.pk,
                        distinct_id="abc",
                        timestamp=datetime(2020, 1, 1),
                        properties={},
                    )
                )

        # To ensure `volume_30_day` and `query_usage_30_day` are returned non
        # None, we need to call this task to have them calculated.
        calculate_event_property_usage_for_team(cls.demo_team.pk)

    def test_list_event_definitions(self):
        response = self.client.get("/api/projects/@current/event_definitions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], len(self.EXPECTED_EVENT_DEFINITIONS))
        self.assertEqual(len(response.json()["results"]), len(self.EXPECTED_EVENT_DEFINITIONS))

        for item in self.EXPECTED_EVENT_DEFINITIONS:
            response_item: Dict[str, Any] = next(
                (_i for _i in response.json()["results"] if _i["name"] == item["name"]), {}
            )
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

        # Search should be case insensitive
        response = self.client.get("/api/projects/@current/event_definitions/?search=App")
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


def create_organization(name: str) -> Organization:
    return Organization.objects.create(name=name)


def create_user(email: str, password: str, organization: Organization):
    return User.objects.create_and_join(organization, email, password)


def create_team(organization: Organization) -> Team:
    """
    This is a helper that just creates a team. It currently uses the orm, but we
    could use either the api, or django admin to create, to get better parity
    with real world  scenarios.

    Previously these tests were running `posthog.demo.create_demo_team` which
    also does a lot of creating of other demo data. This is quite complicated
    and has a couple of downsides:

      1. the tests take 30 seconds just to startup
      2. it makes it difficult to see what data is being used
    """
    return Team.objects.create(
        organization=organization,
        name="Test team",
        ingested_event=True,
        completed_snippet_onboarding=True,
        is_demo=True,
    )


@dataclasses.dataclass
class EventData:
    """
    Little utility struct for creating test event data
    """

    event: str
    team_id: int
    distinct_id: str
    timestamp: datetime
    properties: Dict[str, Any]


def capture_event(event: EventData):
    """
    Creates an event, given an event dict. Currently just puts this data
    directly into clickhouse, but could be created via api to get better parity
    with real world, and could provide the abstraction over if we are using
    clickhouse or postgres as the primary backend
    """
    # NOTE: I'm switching on PRIMARY_DB here although I would like to move this
    # behind an app interface rather than have that detail in the tests. It
    # shouldn't be required to understand the datastore used for us to test.
    if settings.PRIMARY_DB == "clickhouse":
        # NOTE: I'm moving this import here as currently in the CI we're
        # removing the `ee/` directory from the FOSS build
        from ee.clickhouse.models.event import create_event

        team = Team.objects.get(id=event.team_id)
        create_event(
            event_uuid=uuid4(),
            team=team,
            distinct_id=event.distinct_id,
            timestamp=event.timestamp,
            event=event.event,
            properties=event.properties,
        )
    else:
        Event.objects.create(**dataclasses.asdict(event))


def create_event_definitions(name: str, team_id: int) -> EventDefinition:
    """
    Create event definition for a team.
    """
    return EventDefinition.objects.create(name=name, team_id=team_id)
