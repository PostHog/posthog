import json
from datetime import datetime

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest, _create_event, _create_person
from unittest.mock import ANY

from django.core.cache import cache

from posthog.constants import FunnelCorrelationType
from posthog.models.element import Element
from posthog.models.team import Team
from posthog.test.test_journeys import journeys_for

from ee.clickhouse.views.test.funnel.util import (
    EventPattern,
    FunnelCorrelationRequest,
    get_funnel_correlation,
    get_funnel_correlation_ok,
    get_people_for_correlation_ok,
)


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
        assert response.status_code == 403
        assert response.json() == self.unauthenticated_response()

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
            # For Calculating Odds Ratio, we add a prior count of 1 to everything
            #
            # So our odds ratio should be
            #  (success + prior / failure + prior) * (failure_total - failure + prior / success_total - success + prior)
            # = ( 1 + 1 / 1 + 1) * ( 1 - 1 + 1 / 2 - 1 + 1)
            # = 1 / 2

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

            journeys_for(events_by_person=events, team=self.team)

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
                        "event": {
                            "event": "watched video",
                            "elements": [],
                            "properties": {},
                        },
                        "failure_count": 1,
                        "success_count": 1,
                        "success_people_url": ANY,
                        "failure_people_url": ANY,
                        "odds_ratio": 1 / 2,
                        "correlation_type": "failure",
                    }
                ],
                "skewed": False,
            },
            "query_method": "hogql",
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

            journeys_for(events_by_person=events, team=self.team)

            odds_before = get_funnel_correlation_ok(
                client=self.client,
                team_id=self.team.pk,
                request=FunnelCorrelationRequest(
                    events=json.dumps([EventPattern(id="signup"), EventPattern(id="view insights")]),
                    date_to="2020-04-04",
                ),
            )

            other_team = create_team(organization=self.organization)
            journeys_for(events_by_person=events, team=other_team)

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

            journeys_for(events_by_person=events, team=self.team)

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
            "result": {"events": [], "skewed": False},
            "query_method": "hogql",
        }

    def test_event_correlation_endpoint_does_not_include_funnel_steps(self):
        with freeze_time("2020-01-01"):
            self.client.force_login(self.user)

            # Add Person1 with only the funnel steps involved

            events = {
                "Person 1": [
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                    {"event": "some waypoint", "timestamp": datetime(2020, 1, 2)},
                    {"event": "", "timestamp": datetime(2020, 1, 3)},
                ],
                # We need atleast 1 success and failure to return a result
                "Person 2": [
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                    {"event": "some waypoint", "timestamp": datetime(2020, 1, 2)},
                    {"event": "view insights", "timestamp": datetime(2020, 1, 3)},
                ],
            }
            # '' is a weird event name to have, but if it exists, our duty to report it

            journeys_for(events_by_person=events, team=self.team)

            # We need to make sure we clear the cache other tests that have run
            # done interfere with this test
            cache.clear()

            odds = get_funnel_correlation_ok(
                client=self.client,
                team_id=self.team.pk,
                request=FunnelCorrelationRequest(
                    events=json.dumps(
                        [
                            EventPattern(id="signup"),
                            EventPattern(id="some waypoint"),
                            EventPattern(id="view insights"),
                        ]
                    ),
                    date_to="2020-04-04",
                ),
            )

        assert odds == {
            "is_cached": False,
            "last_refresh": "2020-01-01T00:00:00Z",
            "result": {
                "events": [
                    {
                        "correlation_type": "failure",
                        "event": {"event": "", "elements": [], "properties": {}},
                        "failure_count": 1,
                        "odds_ratio": 1 / 4,
                        "success_count": 0,
                        "success_people_url": ANY,
                        "failure_people_url": ANY,
                    }
                ],
                "skewed": False,
            },
            "query_method": "hogql",
        }

    def test_events_correlation_endpoint_provides_people_drill_down_urls(self):
        """
        Here we are setting up three users, and looking to retrieve one
        correlation for watched video, with a url we can use to retrieve people
        that successfully completed the funnel AND watched the video, and
        another for people that did not complete the funnel but also watched the
        video.
        """

        with freeze_time("2020-01-01"):
            self.client.force_login(self.user)

            events = {
                "Person 1": [
                    # Failure / watched
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                    {"event": "watched video", "timestamp": datetime(2020, 1, 2)},
                ],
                "Person 2": [
                    # Success / watched
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                    {"event": "watched video", "timestamp": datetime(2020, 1, 2)},
                    {"event": "view insights", "timestamp": datetime(2020, 1, 3)},
                ],
                "Person 3": [
                    # Success / did not watched. We don't expect to retrieve
                    # this one as part of the
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                    {"event": "view insights", "timestamp": datetime(2020, 1, 3)},
                ],
            }

            journeys_for(events_by_person=events, team=self.team)

            odds = get_funnel_correlation_ok(
                client=self.client,
                team_id=self.team.pk,
                request=FunnelCorrelationRequest(
                    events=json.dumps([EventPattern(id="signup"), EventPattern(id="view insights")]),
                    date_to="2020-04-04",
                ),
            )

            assert odds["result"]["events"][0]["event"]["event"] == "watched video"
            watched_video_correlation = odds["result"]["events"][0]

            assert get_people_for_correlation_ok(client=self.client, correlation=watched_video_correlation) == {
                "success": ["Person 2"],
                "failure": ["Person 1"],
            }

    def test_events_with_properties_correlation_endpoint_provides_people_drill_down_urls(self):
        with freeze_time("2020-01-01"):
            self.client.force_login(self.user)

            events = {
                "Person 1": [
                    # Failure / watched
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                    {
                        "event": "watched video",
                        "properties": {"$browser": "1"},
                        "timestamp": datetime(2020, 1, 2),
                    },
                ],
                "Person 2": [
                    # Success / watched
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                    {
                        "event": "watched video",
                        "properties": {"$browser": "1"},
                        "timestamp": datetime(2020, 1, 2),
                    },
                    {"event": "view insights", "timestamp": datetime(2020, 1, 3)},
                ],
                "Person 3": [
                    # Success / watched. We need to have three event instances
                    # for this test otherwise the endpoint doesn't return results
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                    {
                        "event": "watched video",
                        "properties": {"$browser": "1"},
                        "timestamp": datetime(2020, 1, 2),
                    },
                    {"event": "view insights", "timestamp": datetime(2020, 1, 3)},
                ],
                "Person 4": [
                    # Success / didn't watch. Want to use this user to verify
                    # that we don't pull in unrelated users erroneously
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                    {"event": "view insights", "timestamp": datetime(2020, 1, 3)},
                ],
            }

            journeys_for(events_by_person=events, team=self.team)

            odds = get_funnel_correlation_ok(
                client=self.client,
                team_id=self.team.pk,
                request=FunnelCorrelationRequest(
                    funnel_correlation_type=FunnelCorrelationType.EVENT_WITH_PROPERTIES,
                    funnel_correlation_event_names=json.dumps(["watched video"]),
                    events=json.dumps([EventPattern(id="signup"), EventPattern(id="view insights")]),
                    date_to="2020-04-04",
                ),
            )

            assert odds["result"]["events"][0]["event"]["event"] == "watched video::$browser::1"
            watched_video_correlation = odds["result"]["events"][0]

            assert get_people_for_correlation_ok(client=self.client, correlation=watched_video_correlation) == {
                "success": ["Person 2", "Person 3"],
                "failure": ["Person 1"],
            }

    def test_correlation_endpoint_with_properties(self):
        self.client.force_login(self.user)

        for i in range(10):
            _create_person(
                distinct_ids=[f"user_{i}"],
                team_id=self.team.pk,
                properties={"$browser": "Positive"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id=f"user_{i}",
                timestamp="2020-01-04T14:00:00Z",
            )

        for i in range(10, 20):
            _create_person(
                distinct_ids=[f"user_{i}"],
                team_id=self.team.pk,
                properties={"$browser": "Negative"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="negatively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )

        # We need to make sure we clear the cache other tests that have run
        # done interfere with this test
        cache.clear()

        api_response = get_funnel_correlation_ok(
            client=self.client,
            team_id=self.team.pk,
            request=FunnelCorrelationRequest(
                events=json.dumps([EventPattern(id="user signed up"), EventPattern(id="paid")]),
                date_to="2020-01-14",
                date_from="2020-01-01",
                funnel_correlation_type=FunnelCorrelationType.PROPERTIES,
                funnel_correlation_names=json.dumps(["$browser"]),
            ),
        )

        self.assertFalse(api_response["result"]["skewed"])

        result = api_response["result"]["events"]

        odds_ratios = [item.pop("odds_ratio") for item in result]
        expected_odds_ratios = [121, 1 / 121]

        for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(
            result,
            [
                {
                    "event": {
                        "event": "$browser::Positive",
                        "elements": [],
                        "properties": {},
                    },
                    "success_count": 10,
                    "failure_count": 0,
                    "success_people_url": ANY,
                    "failure_people_url": ANY,
                    # "odds_ratio": 121.0,
                    "correlation_type": "success",
                },
                {
                    "event": {
                        "event": "$browser::Negative",
                        "elements": [],
                        "properties": {},
                    },
                    "success_count": 0,
                    "failure_count": 10,
                    "success_people_url": ANY,
                    "failure_people_url": ANY,
                    # "odds_ratio": 1 / 121,
                    "correlation_type": "failure",
                },
            ],
        )

    def test_properties_correlation_endpoint_provides_people_drill_down_urls(self):
        """
        Here we are setting up three users, two with a specified property but
        differing values, and one with this property absent. We expect to be
        able to use the correlation people drill down urls to retrieve the
        associated people for each.
        """

        with freeze_time("2020-01-01"):
            self.client.force_login(self.user)

            _create_person(
                distinct_ids=["Person 1"],
                team_id=self.team.pk,
                properties={"$browser": "1"},
            )
            _create_person(
                distinct_ids=["Person 2"],
                team_id=self.team.pk,
                properties={"$browser": "1"},
            )
            _create_person(
                distinct_ids=["Person 3"],
                team_id=self.team.pk,
                properties={},
            )

            events = {
                "Person 1": [
                    # Failure / $browser::1
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)}
                ],
                "Person 2": [
                    # Success / $browser::1
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                    {"event": "view insights", "timestamp": datetime(2020, 1, 3)},
                ],
                "Person 3": [
                    # Success / $browser not set
                    {"event": "signup", "timestamp": datetime(2020, 1, 1)},
                    {"event": "view insights", "timestamp": datetime(2020, 1, 3)},
                ],
            }

            journeys_for(events_by_person=events, team=self.team, create_people=False)

            odds = get_funnel_correlation_ok(
                client=self.client,
                team_id=self.team.pk,
                request=FunnelCorrelationRequest(
                    events=json.dumps([EventPattern(id="signup"), EventPattern(id="view insights")]),
                    date_to="2020-04-04",
                    funnel_correlation_type=FunnelCorrelationType.PROPERTIES,
                    funnel_correlation_names=json.dumps(["$browser"]),
                ),
            )

            (browser_correlation,) = (
                correlation
                for correlation in odds["result"]["events"]
                if correlation["event"]["event"] == "$browser::1"
            )

            (notset_correlation,) = (
                correlation for correlation in odds["result"]["events"] if correlation["event"]["event"] == "$browser::"
            )

            assert get_people_for_correlation_ok(client=self.client, correlation=browser_correlation) == {
                "success": ["Person 2"],
                "failure": ["Person 1"],
            }

            assert get_people_for_correlation_ok(client=self.client, correlation=notset_correlation) == {
                "success": ["Person 3"],
                "failure": [],
            }

    def test_correlation_endpoint_request_with_no_steps_doesnt_fail(self):
        """
        This just checks that we get an empty result, this mimics what happens
        with other insight endpoints. It's questionable that perhaps this whould
        be a 400 instead.
        """
        self.client.force_login(self.user)

        with freeze_time("2020-01-01"):
            response = get_funnel_correlation_ok(
                client=self.client,
                team_id=self.team.pk,
                request=FunnelCorrelationRequest(
                    events=json.dumps([]),
                    date_to="2020-01-14",
                    date_from="2020-01-01",
                    funnel_correlation_type=FunnelCorrelationType.PROPERTIES,
                    funnel_correlation_names=json.dumps(["$browser"]),
                ),
            )

        assert response == {
            "is_cached": False,
            "last_refresh": "2020-01-01T00:00:00Z",
            "result": {"events": [], "skewed": False},
            "query_method": "hogql",
        }

    def test_funnel_correlation_with_event_properties_autocapture(self):
        self.client.force_login(self.user)

        # Need a minimum of 3 hits to get a correlation result
        for i in range(3):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id=f"user_{i}",
                elements=[Element(nth_of_type=1, nth_child=0, tag_name="a", href="/movie")],
                timestamp="2020-01-03T14:00:00Z",
                properties={"signup_source": "email", "$event_type": "click"},
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id=f"user_{i}",
                timestamp="2020-01-04T14:00:00Z",
            )

        # Atleast one person that fails, to ensure we get results
        _create_person(distinct_ids=[f"user_fail"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id=f"user_fail",
            timestamp="2020-01-02T14:00:00Z",
        )

        with freeze_time("2020-01-01"):
            response = get_funnel_correlation_ok(
                client=self.client,
                team_id=self.team.pk,
                request=FunnelCorrelationRequest(
                    events=json.dumps([EventPattern(id="user signed up"), EventPattern(id="paid")]),
                    date_to="2020-01-14",
                    date_from="2020-01-01",
                    funnel_correlation_type=FunnelCorrelationType.EVENT_WITH_PROPERTIES,
                    funnel_correlation_event_names=json.dumps(["$autocapture"]),
                ),
            )

        assert response == {
            "result": {
                "events": [
                    {
                        "success_count": 3,
                        "failure_count": 0,
                        "success_people_url": ANY,
                        "failure_people_url": ANY,
                        "odds_ratio": 8.0,
                        "correlation_type": "success",
                        "event": {
                            "event": '$autocapture::elements_chain::click__~~__a:href="/movie"nth-child="0"nth-of-type="1"',
                            "properties": {"$event_type": "click"},
                            "elements": [
                                {
                                    "event": None,
                                    "text": None,
                                    "tag_name": "a",
                                    "attr_class": None,
                                    "href": "/movie",
                                    "attr_id": None,
                                    "nth_child": 0,
                                    "nth_of_type": 1,
                                    "attributes": {},
                                    "order": 0,
                                }
                            ],
                        },
                    }
                ],
                "skewed": False,
            },
            "last_refresh": "2020-01-01T00:00:00Z",
            "is_cached": False,
            "query_method": "hogql",
        }

        assert get_people_for_correlation_ok(client=self.client, correlation=response["result"]["events"][0]) == {
            "success": ["user_0", "user_1", "user_2"],
            "failure": [],
        }


@pytest.fixture(autouse=True)
def clear_django_cache():
    cache.clear()


def create_team(organization):
    return Team.objects.create(name="Test Team", organization=organization)
