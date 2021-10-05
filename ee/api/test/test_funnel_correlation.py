import dataclasses
import json
from datetime import datetime
from typing import Any, Dict, Optional, TypedDict

import pytest
from django.test import Client
from freezegun import freeze_time

from posthog.api.test.test_event_definition import EventData, capture_event
from posthog.api.test.test_retention import identify
from posthog.test.base import BaseTest


@pytest.mark.clickhouse_only
class FunnelCorrelationTest(BaseTest):
    """
    TODO: fill in details of request structure. At the moment it's not needed as
    we just return mock data
    """

    def test_requires_authn(self):
        response = get_funnel_correlation(
            client=self.client,
            team_id=self.team.pk,
            request=FunnelCorrelationRequest(funnel_step=1, date_to="2020-04-04", events=json.dumps([])),
        )
        assert response.status_code == 401

    def test_event_correlation_endpoint(self):
        with freeze_time("2020-01-01"):
            self.client.force_login(self.user)

            # Add in two people:
            #
            # Person 1 - a single signup event
            # Person 2 - a signup event and a view insights event
            #
            # Both of them have a "watched video" event

            create_person(distinct_id="Person 1", team_id=self.team.pk)

            create_event(
                event=EventData(
                    team_id=self.team.pk,
                    distinct_id="Person 1",
                    event="signup",
                    timestamp=datetime(2020, 1, 1),
                    properties={},
                )
            )

            create_event(
                event=EventData(
                    team_id=self.team.pk,
                    distinct_id="Person 1",
                    event="watched video",
                    timestamp=datetime(2020, 1, 2),
                    properties={},
                )
            )

            create_person(distinct_id="Person 2", team_id=self.team.pk)

            create_event(
                event=EventData(
                    team_id=self.team.pk,
                    distinct_id="Person 2",
                    event="signup",
                    timestamp=datetime(2020, 1, 1),
                    properties={},
                )
            )

            create_event(
                event=EventData(
                    team_id=self.team.pk,
                    distinct_id="Person 2",
                    event="watched video",
                    timestamp=datetime(2020, 1, 2),
                    properties={},
                )
            )

            create_event(
                event=EventData(
                    team_id=self.team.pk,
                    distinct_id="Person 2",
                    event="view insights",
                    timestamp=datetime(2020, 1, 3),
                    properties={},
                )
            )

            odds = get_funnel_correlation_ok(
                client=self.client,
                team_id=self.team.pk,
                request=FunnelCorrelationRequest(
                    events=json.dumps([EventPattern(id="signup"), EventPattern(id="view insights")]),
                    funnel_step=1,
                    date_to="2020-04-04",
                ),
            )

        assert odds == {
            "is_cached": False,
            "last_refresh": "2020-01-01T00:00:00Z",
            "result": {
                "events": [
                    # Top 10
                    {"event": "watched video", "success_count": 1, "failure_count": 1, "odds_ratio": 1},
                ]
            },
        }


class EventPattern(TypedDict):
    id: str


@dataclasses.dataclass
class FunnelCorrelationRequest:
    # Needs to be json encoded list of `EventPattern`s
    events: str
    funnel_step: int
    date_to: str
    date_from: Optional[str] = None


def get_funnel_correlation(client: Client, team_id: int, request: FunnelCorrelationRequest):
    return client.get(
        f"/api/projects/{team_id}/insights/funnel/correlation",
        data={key: value for key, value in dataclasses.asdict(request).items() if value is not None},
    )


def get_funnel_correlation_ok(client: Client, team_id: int, request: FunnelCorrelationRequest) -> Dict[str, Any]:
    response = get_funnel_correlation(client=client, team_id=team_id, request=request)

    assert response.status_code == 200
    return response.json()


def create_person(distinct_id: str, team_id: int, properties: Optional[Dict[str, Any]] = None):
    # TODO: change this from being a proxy to identify to being explicit about
    # adding to events/persons/person_distinct_id tables
    return identify(distinct_id=distinct_id, team_id=team_id, properties=properties)


def create_event(event: EventData):
    # TODO: change this from being a proxy to capture_event to being explicit about
    # adding to events tables
    return capture_event(event=event)
