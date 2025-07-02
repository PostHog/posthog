import dataclasses
from datetime import datetime, timedelta
from typing import Any, Optional
from unittest.mock import ANY, patch
from uuid import uuid4

import dateutil.parser
from django.utils import timezone
from freezegun.api import freeze_time
from rest_framework import status
from parameterized import parameterized

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.models import Action, EventDefinition, Organization, Team, ActivityLog
from posthog.test.base import APIBaseTest


@freeze_time("2020-01-02")
class TestEventDefinitionAPI(APIBaseTest):
    demo_team: Team = None  # type: ignore

    EXPECTED_EVENT_DEFINITIONS: list[dict[str, Any]]

    @classmethod
    def setUpTestData(cls):
        cls.organization = create_organization(name="test org")
        cls.demo_team = create_team(organization=cls.organization)
        cls.user = create_user("user", "pass", cls.organization)

        cls.EXPECTED_EVENT_DEFINITIONS = [
            {"name": "installed_app", "last_seen_at": datetime.now() - timedelta(days=1)},
            {"name": "rated_app", "last_seen_at": datetime.now() - timedelta(days=12)},
            {"name": "purchase", "last_seen_at": datetime.now() - timedelta(days=3)},
            {"name": "entered_free_trial", "last_seen_at": datetime.now() - timedelta(hours=1)},
            {"name": "watched_movie", "last_seen_at": None},
            {"name": "$pageview", "last_seen_at": datetime.now() - timedelta(hours=1, minutes=4)},
        ]

        for event_definition in cls.EXPECTED_EVENT_DEFINITIONS:
            create_event_definitions(event_definition, team_id=cls.demo_team.pk)
            capture_event(
                event=EventData(
                    event=event_definition["name"],
                    team_id=cls.demo_team.pk,
                    distinct_id="abc",
                    timestamp=datetime(2020, 1, 1),
                    properties={},
                )
            )

    def test_list_event_definitions(self):
        response = self.client.get("/api/projects/@current/event_definitions/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == len(self.EXPECTED_EVENT_DEFINITIONS)
        assert len(response.json()["results"]) == len(self.EXPECTED_EVENT_DEFINITIONS)

        for item in self.EXPECTED_EVENT_DEFINITIONS:
            response_item: dict[str, Any] = next(
                (_i for _i in response.json()["results"] if _i["name"] == item["name"]),
                {},
            )
            assert abs((dateutil.parser.isoparse(response_item["created_at"]) - timezone.now()).total_seconds()) < 1

    @parameterized.expand(
        [
            (
                "ordering=name",
                [
                    ("$pageview", "2020-01-01T22:56:00Z"),
                    ("entered_free_trial", "2020-01-01T23:00:00Z"),
                    ("installed_app", "2020-01-01T00:00:00Z"),
                    ("purchase", "2019-12-30T00:00:00Z"),
                    ("rated_app", "2019-12-21T00:00:00Z"),
                    ("watched_movie", None),
                ],
            ),
            (
                "ordering=-name",
                [
                    ("watched_movie", None),
                    ("rated_app", "2019-12-21T00:00:00Z"),
                    ("purchase", "2019-12-30T00:00:00Z"),
                    ("installed_app", "2020-01-01T00:00:00Z"),
                    ("entered_free_trial", "2020-01-01T23:00:00Z"),
                    ("$pageview", "2020-01-01T22:56:00Z"),
                ],
            ),
            (
                "ordering=-last_seen_at::date&ordering=name",
                [
                    ("$pageview", "2020-01-01T22:56:00Z"),
                    ("entered_free_trial", "2020-01-01T23:00:00Z"),
                    ("installed_app", "2020-01-01T00:00:00Z"),
                    ("purchase", "2019-12-30T00:00:00Z"),
                    ("rated_app", "2019-12-21T00:00:00Z"),
                    ("watched_movie", None),
                ],
            ),
            (
                "ordering=-last_seen_at::date&ordering=-name",
                [
                    ("installed_app", "2020-01-01T00:00:00Z"),
                    ("entered_free_trial", "2020-01-01T23:00:00Z"),
                    ("$pageview", "2020-01-01T22:56:00Z"),
                    ("purchase", "2019-12-30T00:00:00Z"),
                    ("rated_app", "2019-12-21T00:00:00Z"),
                    ("watched_movie", None),
                ],
            ),
        ]
    )
    def test_list_event_definitions_ordering(self, query_params, expected_results):
        response = self.client.get(f"/api/projects/@current/event_definitions/?{query_params}")
        assert response.status_code == status.HTTP_200_OK
        assert [(r["name"], r["last_seen_at"]) for r in response.json()["results"]] == expected_results

    @patch("posthoganalytics.capture")
    def test_delete_event_definition(self, mock_capture):
        event_definition: EventDefinition = EventDefinition.objects.create(team=self.demo_team, name="test_event")
        response = self.client.delete(f"/api/projects/@current/event_definitions/{event_definition.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert EventDefinition.objects.filter(id=event_definition.id).count() == 0
        mock_capture.assert_called_once_with(
            distinct_id=self.user.distinct_id,
            event="event definition deleted",
            properties={"name": "test_event"},
            groups={
                "instance": ANY,
                "organization": str(self.organization.id),
                "project": str(self.demo_team.uuid),
            },
        )

        activity_log: Optional[ActivityLog] = ActivityLog.objects.first()
        assert activity_log is not None
        assert activity_log.activity == "deleted"
        assert activity_log.item_id == str(event_definition.id)
        assert activity_log.scope == "EventDefinition"
        assert activity_log.detail["name"] == str(event_definition.name)

    def test_pagination_of_event_definitions(self):
        EventDefinition.objects.bulk_create(
            [EventDefinition(team=self.demo_team, name=f"z_event_{i}") for i in range(1, 301)]
        )

        response = self.client.get("/api/projects/@current/event_definitions/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 306
        assert len(response.json()["results"]) == 100  # Default page size
        assert response.json()["results"][0]["name"] == "$pageview"
        assert response.json()["results"][1]["name"] == "entered_free_trial"

        event_checkpoints = [
            184,
            274,
            94,
        ]  # Because Postgres's sorter does this: event_1; event_100, ..., event_2, event_200, ..., it's
        # easier to deterministically set the expected events

        for i in range(0, 3):
            response = self.client.get(response.json()["next"])
            assert response.status_code == status.HTTP_200_OK

            assert response.json()["count"] == 306
            assert len(response.json()["results"]) == (100 if i < 2 else 6)  # Each page has 100 except the last one
            assert response.json()["results"][0]["name"] == f"z_event_{event_checkpoints[i]}"

    def test_cant_see_event_definitions_for_another_team(self):
        org = Organization.objects.create(name="Separate Org")
        team = Team.objects.create(organization=org, name="Default Project")

        EventDefinition.objects.create(team=team, name="should_be_invisible")

        response = self.client.get("/api/projects/@current/event_definitions/")
        assert response.status_code == status.HTTP_200_OK
        for item in response.json()["results"]:
            assert "should_be_invisible" not in item["name"]

        # Also can't fetch for a team to which the user doesn't have permissions
        response = self.client.get(f"/api/projects/{team.pk}/event_definitions/")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json() == self.permission_denied_response("You don't have access to the project.")

    def test_query_event_definitions(self):
        # Regular search
        response = self.client.get("/api/projects/@current/event_definitions/?search=app")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 2  # rated app, installed app

        # Search should be case insensitive
        response = self.client.get("/api/projects/@current/event_definitions/?search=App")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 2  # rated app, installed app

        # Fuzzy search 1
        response = self.client.get("/api/projects/@current/event_definitions/?search=free tri")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1
        for item in response.json()["results"]:
            assert item["name"] in ["entered_free_trial"]

        # Handles URL encoding properly
        response = self.client.get("/api/projects/@current/event_definitions/?search=free%20tri%20")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1
        for item in response.json()["results"]:
            assert item["name"] in ["entered_free_trial"]

        # Fuzzy search 2
        response = self.client.get("/api/projects/@current/event_definitions/?search=ed mov")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1
        for item in response.json()["results"]:
            assert item["name"] in ["watched_movie"]

    def test_event_type_event(self):
        action = Action.objects.create(team=self.demo_team, name="action1_app")

        response = self.client.get("/api/projects/@current/event_definitions/?search=app&event_type=event")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 2
        assert response.json()["results"][0]["name"] != action.name

    def test_event_type_event_custom(self):
        response = self.client.get("/api/projects/@current/event_definitions/?event_type=event_custom")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 5

    def test_event_type_event_posthog(self):
        response = self.client.get("/api/projects/@current/event_definitions/?event_type=event_posthog")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1
        assert response.json()["results"][0]["name"] == "$pageview"


@dataclasses.dataclass
class EventData:
    """
    Little utility struct for creating test event data
    """

    event: str
    team_id: int
    distinct_id: str
    timestamp: datetime
    properties: dict[str, Any]


def capture_event(event: EventData):
    """
    Creates an event, given an event dict. Currently just puts this data
    directly into clickhouse, but could be created via api to get better parity
    with real world, and could provide the abstraction over if we are using
    clickhouse or postgres as the primary backend
    """
    from posthog.models.event.util import create_event

    team = Team.objects.get(id=event.team_id)
    create_event(
        event_uuid=uuid4(),
        team=team,
        distinct_id=event.distinct_id,
        timestamp=event.timestamp,
        event=event.event,
        properties=event.properties,
    )


def create_event_definitions(event_definition: dict, team_id: int) -> EventDefinition:
    created_definition = EventDefinition.objects.create(name=event_definition["name"], team_id=team_id)
    if event_definition["last_seen_at"]:
        created_definition.last_seen_at = event_definition["last_seen_at"]
        created_definition.save()

    return created_definition
