import dataclasses
import json
from datetime import datetime
from typing import Any, Dict, Optional, TypedDict
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.test import Client
from freezegun import freeze_time

from ee.clickhouse.models.event import create_event
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.test.base import BaseTest


@pytest.mark.clickhouse_only
class FunnelCorrelationTest(BaseTest):
    """
    Tests for /api/projects/:project_id/funnel/correlation/
    """

    CLASS_DATA_LEVEL_SETUP = False

    def test_requires_authn(self):
        response = get_funnel_correlation(
            client=self.client,
            team_id=self.team.pk,
            request=FunnelCorrelationRequest(date_to="2020-04-04", events=json.dumps([])),
        )
        assert response.status_code == 401

    def test_event_correlation_endpoint_picks_up_events_for_odds_ratios(self):
        with freeze_time("2020-01-01"):
            self.client.force_login(self.user)

            # Add in two people:
            #
            # Person 1 - a single signup event
            # Person 2 - a signup event and a view insights event
            #
            # Both of them have a "watched video" event
            #
            # We then create Person 3, one successful, the other
            # not. Both have not watched the video.
            #
            # So our contingency table for "watched video" should be
            #
            # |                  | success  | failure  | total    |
            # | ---------------- | -------- | -------- | -------- |
            # | watched          | 1        | 1        | 2        |
            # | did not watched  | 1        | 0        | 1        |
            # | total            | 2        | 1        | 3        |
            #

            events = {
                "Person 1": [
                    #  Failure / watched
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                    {"event": "watched video", "timestamp": datetime(2020, 1, 2)},
                ],
                "Person 2": [
                    #  Success / watched
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                    {"event": "watched video", "timestamp": datetime(2020, 1, 2)},
                    {"event": "view insights", "timestamp": datetime(2020, 1, 3)},
                ],
                "Person 3": [
                    # Success / did not watched
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                    {"event": "view insights", "timestamp": datetime(2020, 1, 3)},
                ],
            }

            create_events(events_by_person=events, team=self.team)

            odds = get_funnel_correlation_ok(
                client=self.client,
                team_id=self.team.pk,
                request=FunnelCorrelationRequest(
                    events=json.dumps([EventPattern(id="signup"), EventPattern(id="view insights")]),
                    date_to="2020-04-04",
                ),
            )

        assert odds == {
            "is_cached": False,
            "last_refresh": "2020-01-01T00:00:00Z",
            "result": {
                "events": [
                    {
                        "event": "watched video",
                        "success_count": 1,
                        "failure_count": 1,
                        "odds_ratio": 0.5,
                        "correlation_type": "failure",
                    },
                ]
            },
        }

    def test_event_correlation_is_partitioned_by_team(self):
        """
        Ensure there's no crosstalk between teams

        We check this by:

         1. loading events into team 1
         2. checking correlation for team 1
         3. loading events into team 2
         4. checking correlation for team 1 again, they should be the same

        """
        with freeze_time("2020-01-01"):
            self.client.force_login(self.user)

            events = {
                "Person 1": [
                    {"event": "watched video", "timestamp": datetime(2019, 1, 2)},
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                ],
                "Person 2": [
                    {"event": "watched video", "timestamp": datetime(2019, 1, 2)},
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                    {"event": "view insights", "timestamp": datetime(2020, 1, 3)},
                ],
            }

            create_events(events_by_person=events, team=self.team)

            odds_before = get_funnel_correlation_ok(
                client=self.client,
                team_id=self.team.pk,
                request=FunnelCorrelationRequest(
                    events=json.dumps([EventPattern(id="signup"), EventPattern(id="view insights")]),
                    date_to="2020-04-04",
                ),
            )

            other_team = create_team(organization=self.organization)
            create_events(events_by_person=events, team=other_team)

            # We need to make sure we clear the cache so we get the same results again
            cache.clear()

            odds_after = get_funnel_correlation_ok(
                client=self.client,
                team_id=self.team.pk,
                request=FunnelCorrelationRequest(
                    events=json.dumps([EventPattern(id="signup"), EventPattern(id="view insights")]),
                    date_to="2020-04-04",
                ),
            )

            assert odds_before == odds_after

    def test_event_correlation_endpoint_does_not_include_historical_events(self):
        with freeze_time("2020-01-01"):
            self.client.force_login(self.user)

            # Add in two people:
            #
            # Person 1 - a single signup event
            # Person 2 - a signup event and a view insights event
            #
            # Both of them have a "watched video" event but they are before the
            # signup event

            events = {
                "Person 1": [
                    {"event": "watched video", "timestamp": datetime(2019, 1, 2)},
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                ],
                "Person 2": [
                    {"event": "watched video", "timestamp": datetime(2019, 1, 2)},
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                    {"event": "view insights", "timestamp": datetime(2020, 1, 3)},
                ],
            }

            create_events(events_by_person=events, team=self.team)

            # We need to make sure we clear the cache other tests that have run
            # done interfere with this test
            cache.clear()

            odds = get_funnel_correlation_ok(
                client=self.client,
                team_id=self.team.pk,
                request=FunnelCorrelationRequest(
                    events=json.dumps([EventPattern(id="signup"), EventPattern(id="view insights")]),
                    date_to="2020-04-04",
                ),
            )

        assert odds == {
            "is_cached": False,
            "last_refresh": "2020-01-01T00:00:00Z",
            "result": {"events": []},
        }

    def test_event_correlation_endpoint_does_not_funnel_steps(self):
        with freeze_time("2020-01-01"):
            self.client.force_login(self.user)

            # Add Person1 with only the funnel steps involved

            events = {
                "Person 1": [
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                    {"event": "some waypoint", "timestamp": datetime(2020, 1, 2)},
                    {"event": "", "timestamp": datetime(2020, 1, 3)},
                ],
            }

            create_events(events_by_person=events, team=self.team)

            # We need to make sure we clear the cache other tests that have run
            # done interfere with this test
            cache.clear()

            odds = get_funnel_correlation_ok(
                client=self.client,
                team_id=self.team.pk,
                request=FunnelCorrelationRequest(
                    events=json.dumps(
                        [EventPattern(id="signup"), EventPattern(id="some waypoint"), EventPattern(id="view insights")]
                    ),
                    date_to="2020-04-04",
                ),
            )

        assert odds == {
            "is_cached": False,
            "last_refresh": "2020-01-01T00:00:00Z",
            "result": {"events": []},
        }


@pytest.fixture(autouse=True)
def clear_django_cache():
    cache.clear()


def create_team(organization):
    return Team.objects.create(name="Test Team", organization=organization)


def create_events(events_by_person, team: Team):
    """
    Helper for creating specific events for a team.
    """
    for distinct_id, events in events_by_person.items():
        create_person(distinct_ids=[distinct_id], team=team)
        for event in events:
            _create_event(
                team=team,
                distinct_id=distinct_id,
                event=event["event"],
                timestamp=event["timestamp"],
                properties=event.get("properties", {}),
            )


class EventPattern(TypedDict):
    id: str


@dataclasses.dataclass
class FunnelCorrelationRequest:
    # Needs to be json encoded list of `EventPattern`s
    events: str
    date_to: str
    funnel_step: Optional[int] = None
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


def create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return person


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)
