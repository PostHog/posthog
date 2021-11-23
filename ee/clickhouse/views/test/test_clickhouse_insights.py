import json
from typing import Any, Dict, List, Union
from unittest.mock import patch
from uuid import uuid4

from django.test.client import Client
from freezegun.api import freeze_time
from rest_framework import status

from ee.api.test.base import LicensedTestMixin
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.util import deep_dump_object
from ee.clickhouse.test.test_journeys import journeys_for
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from ee.models.explicit_team_membership import ExplicitTeamMembership
from posthog.api.test.test_insight import insight_test_factory
from posthog.api.test.test_trends import (
    TrendsRequest,
    TrendsRequestBreakdown,
    get_trends_aggregate_ok,
    get_trends_people_ok,
    get_trends_time_series_ok,
)
from posthog.models.organization import OrganizationMembership
from posthog.models.person import Person
from posthog.test.base import APIBaseTest, test_with_materialized_columns


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=str(person.uuid))


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class ClickhouseTestInsights(
    ClickhouseTestMixin, LicensedTestMixin, insight_test_factory(_create_event, _create_person)  # type: ignore
):
    # Extra permissioning tests here
    def test_insight_trends_allowed_if_project_open_and_org_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = False
        self.team.save()
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_insight_trends_forbidden_if_project_private_and_org_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = True
        self.team.save()
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}"
        )
        self.assertDictEqual(self.permission_denied_response("You don't have access to the project."), response.json())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_insight_trends_allowed_if_project_private_and_org_member_and_project_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.team.access_control = True
        self.team.save()
        self_team_membership = ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=self.organization_membership, level=ExplicitTeamMembership.Level.MEMBER
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?events={json.dumps([{'id': '$pageview'}])}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class ClickhouseTestFunnelTypes(ClickhouseTestMixin, APIBaseTest):
    def test_funnel_unordered_basic_post(self):
        _create_person(distinct_ids=["1"], team=self.team)
        _create_event(team=self.team, event="step one", distinct_id="1")
        _create_event(team=self.team, event="step two", distinct_id="1")

        _create_person(distinct_ids=["2"], team=self.team)
        _create_event(team=self.team, event="step two", distinct_id="2")
        _create_event(team=self.team, event="step one", distinct_id="2")

        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel/",
            {
                "events": [
                    {"id": "step one", "type": "events", "order": 0},
                    {"id": "step two", "type": "events", "order": 1},
                ],
                "funnel_window_days": 14,
                "funnel_order_type": "unordered",
                "insight": "funnels",
            },
        ).json()

        self.assertEqual(len(response["result"]), 2)
        self.assertEqual(response["result"][0]["name"], "step one")
        self.assertEqual(response["result"][1]["name"], "step two")
        self.assertEqual(response["result"][0]["count"], 2)
        self.assertEqual(response["result"][1]["count"], 2)

        # Should have 2 people, all got to the end of the funnel
        assert get_funnel_people_breakdown_by_step(client=self.client, funnel_response=response) == [
            {"name": "step one", "converted": ["1", "2"], "dropped": []},
            {"name": "step two", "converted": ["1", "2"], "dropped": []},
        ]

    def test_unordered_funnel_with_breakdown_by_event_property(self):
        # Setup three funnel people, with two different $browser values
        person1_properties = {"key": "val", "$browser": "Chrome"}
        person2_properties = {"key": "val", "$browser": "Safari"}
        person3_properties = person2_properties

        events = {
            "person1": [
                {"event": "sign up", "timestamp": "2020-01-01", "properties": person1_properties},
                {"event": "buy", "timestamp": "2020-01-02", "properties": person1_properties},
                {"event": "play movie", "timestamp": "2020-01-03", "properties": person1_properties},
            ],
            "person2": [
                {"event": "buy", "timestamp": "2020-01-01", "properties": person2_properties},
                {"event": "sign up", "timestamp": "2020-01-02", "properties": person2_properties},
                {"event": "play movie", "timestamp": "2020-01-03", "properties": person2_properties},
            ],
            "person3": [{"event": "sign up", "timestamp": "2020-01-01", "properties": person3_properties},],
        }

        journeys_for(team=self.team, events_by_person=events)

        response = self.client.post(
            f"/api/projects/{self.team.pk}/insights/funnel/",
            {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2}],
                "insight": "FUNNELS",
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "funnel_order_type": "unordered",
                "breakdown_type": "event",
                "breakdown": "$browser",
            },
        ).json()

        assert get_funnel_breakdown_people_breakdown_by_step(client=self.client, funnel_response=response) == [
            {
                "breakdown_value": "Chrome",
                "steps": [
                    {"name": "sign up", "converted": ["person1"], "dropped": []},
                    {"name": "play movie", "converted": ["person1"], "dropped": []},
                    {"name": "buy", "converted": ["person1"], "dropped": []},
                ],
            },
            {
                "breakdown_value": "Safari",
                "steps": [
                    {"name": "sign up", "converted": ["person2", "person3"], "dropped": []},
                    {"name": "play movie", "converted": ["person2"], "dropped": ["person3"]},
                    {"name": "buy", "converted": ["person2"], "dropped": []},
                ],
            },
        ]

    def test_funnel_strict_basic_post(self):
        _create_person(distinct_ids=["1"], team=self.team)
        _create_event(team=self.team, event="step one", distinct_id="1")
        _create_event(team=self.team, event="step two", distinct_id="1")

        _create_person(distinct_ids=["2"], team=self.team)
        _create_event(team=self.team, event="step one", distinct_id="2")
        _create_event(team=self.team, event="blahh", distinct_id="2")
        _create_event(team=self.team, event="step two", distinct_id="2")

        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel/",
            {
                "events": [
                    {"id": "step one", "type": "events", "order": 0},
                    {"id": "step two", "type": "events", "order": 1},
                ],
                "funnel_window_days": 14,
                "funnel_order_type": "strict",
                "insight": "funnels",
            },
        ).json()

        self.assertEqual(len(response["result"]), 2)
        self.assertEqual(response["result"][0]["name"], "step one")
        self.assertEqual(response["result"][1]["name"], "step two")
        self.assertEqual(response["result"][0]["count"], 2)
        self.assertEqual(response["result"][1]["count"], 1)

        # Should have 2 people, all got through step one, but as this is a
        # strict funnel, person with distinct_id "2" is not converted as they
        # performed bleh in between step one and step two
        assert get_funnel_people_breakdown_by_step(client=self.client, funnel_response=response) == [
            {"name": "step one", "converted": ["1", "2"], "dropped": []},
            {"name": "step two", "converted": ["1"], "dropped": ["2"]},
        ]

    def test_strict_funnel_with_breakdown_by_event_property(self):
        # Setup three funnel people, with two different $browser values
        chrome_properties = {"key": "val", "$browser": "Chrome"}
        safari_properties = {"key": "val", "$browser": "Safari"}

        events = {
            "person1": [
                {"event": "sign up", "timestamp": "2020-01-01", "properties": chrome_properties},
                {"event": "play movie", "timestamp": "2020-01-02", "properties": chrome_properties},
                {"event": "buy", "timestamp": "2020-01-03", "properties": chrome_properties},
            ],
            "person2": [
                {"event": "sign up", "timestamp": "2020-01-01", "properties": safari_properties},
                {"event": "play movie", "timestamp": "2020-01-02", "properties": safari_properties},
                {
                    # This person should not convert here as we're in strict mode,
                    # and this event is not in the funnel definition
                    "event": "event not in funnel",
                    "timestamp": "2020-01-03",
                    "properties": safari_properties,
                },
                {"event": "buy", "timestamp": "2020-01-04", "properties": safari_properties},
            ],
            "person3": [{"event": "sign up", "timestamp": "2020-01-01", "properties": safari_properties},],
        }

        journeys_for(team=self.team, events_by_person=events)

        response = self.client.post(
            f"/api/projects/{self.team.pk}/insights/funnel/",
            {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2}],
                "insight": "FUNNELS",
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "funnel_order_type": "strict",
                "breakdown_type": "event",
                "breakdown": "$browser",
            },
        ).json()

        assert get_funnel_breakdown_people_breakdown_by_step(client=self.client, funnel_response=response) == [
            {
                "breakdown_value": "Chrome",
                "steps": [
                    {"name": "sign up", "converted": ["person1"], "dropped": []},
                    {"name": "play movie", "converted": ["person1"], "dropped": []},
                    {"name": "buy", "converted": ["person1"], "dropped": []},
                ],
            },
            {
                "breakdown_value": "Safari",
                "steps": [
                    {"name": "sign up", "converted": ["person2", "person3"], "dropped": []},
                    {"name": "play movie", "converted": ["person2"], "dropped": ["person3"]},
                    {"name": "buy", "converted": [], "dropped": ["person2"]},
                ],
            },
        ]

    def test_funnel_with_breakdown_by_event_property(self):
        # Setup three funnel people, with two different $browser values
        # NOTE: this is mostly copied from
        # https://github.com/PostHog/posthog/blob/a0f5a0a46a0deca2e17a66dfb530ca18ac99e58c/ee/clickhouse/queries/funnels/test/breakdown_cases.py#L24:L24
        #
        person1_properties = {"key": "val", "$browser": "Chrome"}
        person2_properties = {"key": "val", "$browser": "Safari"}
        person3_properties = person2_properties

        events = {
            "person1": [
                {"event": "sign up", "timestamp": "2020-01-01", "properties": person1_properties},
                {"event": "play movie", "timestamp": "2020-01-02", "properties": person1_properties},
                {"event": "buy", "timestamp": "2020-01-03", "properties": person1_properties},
            ],
            "person2": [
                {"event": "sign up", "timestamp": "2020-01-01", "properties": person2_properties},
                {"event": "play movie", "timestamp": "2020-01-02", "properties": person2_properties},
                {"event": "buy", "timestamp": "2020-01-03", "properties": person2_properties},
            ],
            "person3": [{"event": "sign up", "timestamp": "2020-01-01", "properties": person3_properties},],
        }

        journeys_for(team=self.team, events_by_person=events)

        response = self.client.post(
            f"/api/projects/{self.team.pk}/insights/funnel/",
            {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2}],
                "insight": "FUNNELS",
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": "$browser",
            },
        ).json()

        assert get_funnel_breakdown_people_breakdown_by_step(client=self.client, funnel_response=response) == [
            {
                "breakdown_value": "Chrome",
                "steps": [
                    {"name": "sign up", "converted": ["person1"], "dropped": []},
                    {"name": "play movie", "converted": ["person1"], "dropped": []},
                    {"name": "buy", "converted": ["person1"], "dropped": []},
                ],
            },
            {
                "breakdown_value": "Safari",
                "steps": [
                    {"name": "sign up", "converted": ["person2", "person3"], "dropped": []},
                    {"name": "play movie", "converted": ["person2"], "dropped": ["person3"]},
                    {"name": "buy", "converted": ["person2"], "dropped": []},
                ],
            },
        ]

    def test_funnel_trends_basic_post(self):
        _create_person(distinct_ids=["user_one"], team=self.team)
        _create_person(distinct_ids=["user_two"], team=self.team)

        # user_one, funnel steps: one, two three
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-01 01:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-03 00:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-05 00:00:00")

        # user_two, funnel steps: one, two
        _create_event(event="step one", distinct_id="user_two", team=self.team, timestamp="2021-05-02 00:00:00")
        _create_event(event="step two", distinct_id="user_two", team=self.team, timestamp="2021-05-04 00:00:00")
        _create_event(event="step three", distinct_id="user_two", team=self.team, timestamp="2021-05-05 00:00:00")

        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel/",
            {
                "events": [
                    {"id": "step one", "type": "events", "order": 0},
                    {"id": "step two", "type": "events", "order": 1},
                    {"id": "step three", "type": "events", "order": 2},
                ],
                "funnel_window_days": 7,
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 23:59:59",
                "funnel_viz_type": "trends",
            },
        ).json()

        self.assertEqual(len(response["result"]), 1)
        self.assertEqual(response["result"][0]["count"], 7)
        self.assertEqual(response["result"][0]["data"], [100, 100, 0, 0, 0, 0, 0])

    def test_funnel_trends_unordered_basic_post(self):
        _create_person(distinct_ids=["user_one"], team=self.team)
        _create_person(distinct_ids=["user_two"], team=self.team)
        # user_one, funnel steps: one, two three
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-01 01:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-03 00:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-05 00:00:00")

        # user_two, funnel steps: one, two, three
        _create_event(event="step three", distinct_id="user_two", team=self.team, timestamp="2021-05-02 00:00:00")
        _create_event(event="step one", distinct_id="user_two", team=self.team, timestamp="2021-05-03 00:00:00")
        _create_event(event="step two", distinct_id="user_two", team=self.team, timestamp="2021-05-04 00:00:00")

        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel/",
            {
                "events": [
                    {"id": "step one", "type": "events", "order": 0},
                    {"id": "step two", "type": "events", "order": 1},
                    {"id": "step three", "type": "events", "order": 2},
                ],
                "funnel_window_days": 7,
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 23:59:59",
                "funnel_viz_type": "trends",
                "funnel_order_type": "unordered",
            },
        ).json()

        self.assertEqual(len(response["result"]), 1)
        self.assertEqual(response["result"][0]["count"], 7)
        self.assertEqual(response["result"][0]["data"], [100, 100, 0, 0, 0, 0, 0])

    def test_funnel_trends_basic_post_backwards_compatibility(self):
        _create_person(distinct_ids=["user_one"], team=self.team)
        _create_person(distinct_ids=["user_two"], team=self.team)

        # user_one, funnel steps: one, two three
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-01 01:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-03 00:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-05 00:00:00")

        # user_two, funnel steps: one, two
        _create_event(event="step one", distinct_id="user_two", team=self.team, timestamp="2021-05-02 00:00:00")
        _create_event(event="step two", distinct_id="user_two", team=self.team, timestamp="2021-05-04 00:00:00")
        _create_event(event="step three", distinct_id="user_two", team=self.team, timestamp="2021-05-05 00:00:00")

        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel/",
            {
                "events": [
                    {"id": "step one", "type": "events", "order": 0},
                    {"id": "step two", "type": "events", "order": 1},
                    {"id": "step three", "type": "events", "order": 2},
                ],
                "funnel_window_days": 7,
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 23:59:59",
                "display": "ActionsLineGraph",
            },
        ).json()

        self.assertEqual(len(response["result"]), 1)
        self.assertEqual(response["result"][0]["count"], 7)
        self.assertEqual(response["result"][0]["data"], [100, 100, 0, 0, 0, 0, 0])

    def test_funnel_trends_strict_basic_post(self):
        _create_person(distinct_ids=["user_one"], team=self.team)
        _create_person(distinct_ids=["user_two"], team=self.team)
        _create_person(distinct_ids=["user_three"], team=self.team)

        # user_one, funnel steps: one, two three
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-01 01:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-03 00:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-05 00:00:00")

        # user_two, funnel steps: one, two
        _create_event(event="step one", distinct_id="user_two", team=self.team, timestamp="2021-05-02 00:00:00")
        _create_event(event="step two", distinct_id="user_two", team=self.team, timestamp="2021-05-04 00:00:00")
        _create_event(event="blah", distinct_id="user_two", team=self.team, timestamp="2021-05-04 02:00:00")
        _create_event(event="step three", distinct_id="user_two", team=self.team, timestamp="2021-05-05 00:00:00")

        # user_three, funnel steps: one, two, three
        _create_event(event="step one", distinct_id="user_three", team=self.team, timestamp="2021-05-02 00:00:00")
        _create_event(event="step two", distinct_id="user_three", team=self.team, timestamp="2021-05-04 00:00:00")
        _create_event(event="step three", distinct_id="user_three", team=self.team, timestamp="2021-05-05 00:00:00")

        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel/",
            {
                "events": [
                    {"id": "step one", "type": "events", "order": 0},
                    {"id": "step two", "type": "events", "order": 1},
                    {"id": "step three", "type": "events", "order": 2},
                ],
                "funnel_window_days": 7,
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 23:59:59",
                "funnel_viz_type": "trends",
                "funnel_order_type": "strict",
            },
        ).json()

        self.assertEqual(len(response["result"]), 1)
        self.assertEqual(response["result"][0]["count"], 7)
        self.assertEqual(response["result"][0]["data"], [100, 50, 0, 0, 0, 0, 0])

    def test_funnel_time_to_convert_auto_bins(self):
        _create_person(distinct_ids=["user a"], team=self.team)
        _create_person(distinct_ids=["user b"], team=self.team)
        _create_person(distinct_ids=["user c"], team=self.team)

        _create_event(event="step one", distinct_id="user a", team=self.team, timestamp="2021-06-08 18:00:00")
        _create_event(event="blah", distinct_id="user a", team=self.team, timestamp="2021-06-08 18:30:00")
        _create_event(event="step two", distinct_id="user a", team=self.team, timestamp="2021-06-08 19:00:00")
        # Converted from 0 to 1 in 3600 s
        _create_event(event="step three", distinct_id="user a", team=self.team, timestamp="2021-06-08 21:00:00")

        _create_event(event="step one", distinct_id="user b", team=self.team, timestamp="2021-06-09 13:00:00")
        _create_event(event="step two", distinct_id="user b", team=self.team, timestamp="2021-06-09 13:37:00")
        # Converted from 0 to 1 in 2200 s

        _create_event(event="step one", distinct_id="user c", team=self.team, timestamp="2021-06-11 07:00:00")
        _create_event(event="step two", distinct_id="user c", team=self.team, timestamp="2021-06-12 06:00:00")
        # Converted from 0 to 1 in 82_800 s

        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel/",
            {
                "insight": "funnels",
                "funnel_viz_type": "time_to_convert",
                "interval": "day",
                "date_from": "2021-06-07 00:00:00",
                "date_to": "2021-06-13 23:59:59",
                "funnel_to_step": 1,
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        response_data.pop("last_refresh")
        self.assertEqual(
            response_data,
            {
                "is_cached": False,
                "result": {
                    "bins": [[2220.0, 2], [29080.0, 0], [55940.0, 0], [82800.0, 1]],
                    "average_conversion_time": 29540.0,
                },
            },
        )

    def test_funnel_time_to_convert_auto_bins_strict(self):
        _create_person(distinct_ids=["user a"], team=self.team)
        _create_person(distinct_ids=["user b"], team=self.team)
        _create_person(distinct_ids=["user c"], team=self.team)

        _create_event(event="step one", distinct_id="user a", team=self.team, timestamp="2021-06-08 18:00:00")
        _create_event(event="step two", distinct_id="user a", team=self.team, timestamp="2021-06-08 19:00:00")
        # Converted from 0 to 1 in 3600 s
        _create_event(event="step three", distinct_id="user a", team=self.team, timestamp="2021-06-08 21:00:00")

        _create_event(event="step one", distinct_id="user b", team=self.team, timestamp="2021-06-09 13:00:00")
        _create_event(event="step two", distinct_id="user b", team=self.team, timestamp="2021-06-09 13:37:00")
        # Converted from 0 to 1 in 2200 s

        _create_event(event="step one", distinct_id="user c", team=self.team, timestamp="2021-06-11 07:00:00")
        _create_event(event="step two", distinct_id="user c", team=self.team, timestamp="2021-06-12 06:00:00")
        # Converted from 0 to 1 in 82_800 s

        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel/",
            {
                "insight": "funnels",
                "funnel_viz_type": "time_to_convert",
                "funnel_order_type": "strict",
                "interval": "day",
                "date_from": "2021-06-07 00:00:00",
                "date_to": "2021-06-13 23:59:59",
                "funnel_to_step": 1,
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        response_data.pop("last_refresh")
        self.assertEqual(
            response_data,
            {
                "is_cached": False,
                "result": {
                    "bins": [[2220.0, 2], [29080.0, 0], [55940.0, 0], [82800.0, 1]],
                    "average_conversion_time": 29540.0,
                },
            },
        )

    def test_funnel_time_to_convert_auto_bins_unordered(self):
        _create_person(distinct_ids=["user a"], team=self.team)
        _create_person(distinct_ids=["user b"], team=self.team)
        _create_person(distinct_ids=["user c"], team=self.team)

        _create_event(event="step one", distinct_id="user a", team=self.team, timestamp="2021-06-08 18:00:00")
        _create_event(event="step two", distinct_id="user a", team=self.team, timestamp="2021-06-08 19:00:00")
        # Converted from 0 to 1 in 3600 s
        _create_event(event="step three", distinct_id="user a", team=self.team, timestamp="2021-06-08 21:00:00")

        _create_event(event="step two", distinct_id="user b", team=self.team, timestamp="2021-06-09 13:00:00")
        _create_event(event="step one", distinct_id="user b", team=self.team, timestamp="2021-06-09 13:37:00")
        # Converted from 0 to 1 in 2200 s

        _create_event(event="step one", distinct_id="user c", team=self.team, timestamp="2021-06-11 07:00:00")
        _create_event(event="step two", distinct_id="user c", team=self.team, timestamp="2021-06-12 06:00:00")
        # Converted from 0 to 1 in 82_800 s

        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel/",
            {
                "insight": "funnels",
                "funnel_viz_type": "time_to_convert",
                "funnel_order_type": "unordered",
                "interval": "day",
                "date_from": "2021-06-07 00:00:00",
                "date_to": "2021-06-13 23:59:59",
                "funnel_to_step": 1,
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        response_data.pop("last_refresh")
        self.assertEqual(
            response_data,
            {
                "is_cached": False,
                "result": {
                    "bins": [[2220.0, 2], [29080.0, 0], [55940.0, 0], [82800.0, 1]],
                    "average_conversion_time": 29540.0,
                },
            },
        )

    def test_funnel_invalid_action_handled(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel/",
            {"actions": [{"id": 666, "type": "actions", "order": 0},]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), self.validation_error_response("Action ID 666 does not exist!"))

    def test_funnel_basic_exclusions(self):
        _create_person(distinct_ids=["1"], team=self.team)
        _create_event(team=self.team, event="step one", distinct_id="1")
        _create_event(team=self.team, event="step x", distinct_id="1")
        _create_event(team=self.team, event="step two", distinct_id="1")

        _create_person(distinct_ids=["2"], team=self.team)
        _create_event(team=self.team, event="step one", distinct_id="2")
        _create_event(team=self.team, event="step two", distinct_id="2")

        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel/",
            {
                "events": [
                    {"id": "step one", "type": "events", "order": 0},
                    {"id": "step two", "type": "events", "order": 1},
                ],
                "exclusions": [{"id": "step x", "type": "events", "funnel_from_step": 0, "funnel_to_step": 1},],
                "funnel_window_days": 14,
                "insight": "funnels",
            },
        ).json()

        self.assertEqual(len(response["result"]), 2)
        self.assertEqual(response["result"][0]["name"], "step one")
        self.assertEqual(response["result"][1]["name"], "step two")
        self.assertEqual(response["result"][0]["count"], 1)
        self.assertEqual(response["result"][1]["count"], 1)

        # Should only pick up the person with distinct id "2" as the "1" person
        # performed the "step x" event, which we're explicitly asking to be
        # excluded in the request payload
        assert get_funnel_people_breakdown_by_step(client=self.client, funnel_response=response) == [
            {"name": "step one", "converted": ["2"], "dropped": []},
            {"name": "step two", "converted": ["2"], "dropped": []},
        ]

    def test_funnel_invalid_exclusions(self):
        _create_person(distinct_ids=["1"], team=self.team)
        _create_event(team=self.team, event="step one", distinct_id="1")
        _create_event(team=self.team, event="step x", distinct_id="1")
        _create_event(team=self.team, event="step two", distinct_id="1")

        _create_person(distinct_ids=["2"], team=self.team)
        _create_event(team=self.team, event="step one", distinct_id="2")
        _create_event(team=self.team, event="step two", distinct_id="2")

        for exclusion_id, exclusion_from_step, exclusion_to_step, error in [
            ("step one", 0, 1, True),
            ("step two", 0, 1, True),
            ("step two", 0, 2, True),
            ("step one", 0, 2, True),
            ("step three", 0, 2, True),
            ("step three", 0, 1, False),
        ]:
            response = self.client.post(
                f"/api/projects/{self.team.id}/insights/funnel/",
                {
                    "events": [
                        {"id": "step one", "type": "events", "order": 0},
                        {"id": "step two", "type": "events", "order": 1},
                        {"id": "step three", "type": "events", "order": 2},
                    ],
                    "exclusions": [
                        {
                            "id": exclusion_id,
                            "type": "events",
                            "funnel_from_step": exclusion_from_step,
                            "funnel_to_step": exclusion_to_step,
                        },
                    ],
                    "funnel_window_days": 14,
                    "insight": "funnels",
                },
            )

            if error:
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json(), self.validation_error_response("Exclusion event can't be the same as funnel step")
                )
            else:
                self.assertEqual(response.status_code, 200)

    def test_single_property_breakdown(self):
        journeys_for(
            {
                "person1": [
                    {"event": "$pageview", "properties": {"$browser": "Chrome", "$browser_version": 95}},
                    {"event": "$pageleave", "properties": {"$browser": "Chrome", "$browser_version": 95}},
                ],
                "person2": [
                    {"event": "$pageview", "properties": {"$browser": "Safari", "$browser_version": 11}},
                    {"event": "$pageview", "properties": {"$browser": "Safari", "$browser_version": 11}},
                ],
            },
            self.team,
        )

        filter_with_breakdown = {
            "insight": "FUNNELS",
            "date_from": "-14d",
            "actions": [],
            "events": [
                {"id": "$pageview", "name": "$pageview", "type": "events", "order": 0},
                {"id": "$pageleave", "name": "$pageleave", "type": "events", "order": 1},
            ],
            "display": "FunnelViz",
            "interval": "day",
            "properties": [],
            "funnel_viz_type": "steps",
            "exclusions": [],
            "breakdown": "$browser",
            "breakdown_type": "event",
            "funnel_from_step": 0,
            "funnel_to_step": 1,
        }

        response = self.client.post(f"/api/projects/{self.team.id}/insights/funnel?refresh=true", filter_with_breakdown)
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        result = response_data["result"]

        self.assertEqual(result[0][0]["name"], "$pageview")
        self.assertEqual(result[0][0]["count"], 1)
        self.assertEqual("Chrome", result[0][0]["breakdown"])
        self.assertEqual("Chrome", result[0][0]["breakdown_value"])

        self.assertEqual(result[0][1]["name"], "$pageleave")
        self.assertEqual(result[0][1]["count"], 1)
        self.assertEqual("Chrome", result[0][1]["breakdown"])
        self.assertEqual("Chrome", result[0][1]["breakdown_value"])

        self.assertEqual(result[1][0]["name"], "$pageview")
        self.assertEqual(result[1][0]["count"], 1)
        self.assertEqual("Safari", result[1][0]["breakdown"])
        self.assertEqual("Safari", result[1][0]["breakdown_value"])

        self.assertEqual(result[1][1]["name"], "$pageleave")
        self.assertEqual(result[1][1]["count"], 0)
        self.assertEqual("Safari", result[1][1]["breakdown"])
        self.assertEqual("Safari", result[1][1]["breakdown_value"])

    def test_multi_property_breakdown(self):
        journeys_for(
            {
                "person1": [
                    {"event": "$pageview", "properties": {"$browser": "Chrome", "$browser_version": 95}},
                    {"event": "$pageleave", "properties": {"$browser": "Chrome", "$browser_version": 95}},
                ],
                "person2": [
                    {"event": "$pageview", "properties": {"$browser": "Safari", "$browser_version": 11}},
                    {"event": "$pageview", "properties": {"$browser": "Safari", "$browser_version": 11}},
                ],
            },
            self.team,
        )

        filter_with_breakdown = {
            "insight": "FUNNELS",
            "date_from": "-14d",
            "actions": [],
            "events": [
                {"id": "$pageview", "name": "$pageview", "type": "events", "order": 0},
                {"id": "$pageleave", "name": "$pageleave", "type": "events", "order": 1},
            ],
            "display": "FunnelViz",
            "interval": "day",
            "properties": [],
            "funnel_viz_type": "steps",
            "exclusions": [],
            "breakdowns": '[{"property": "$browser", "type": "event"}, {"property": "$browser_version", "type": "event"}]',
            "breakdown_type": "event",
            "funnel_from_step": 0,
            "funnel_to_step": 1,
        }

        response = self.client.post(f"/api/projects/{self.team.id}/insights/funnel?refresh=true", filter_with_breakdown)
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        result = response_data["result"]

        self.assertEqual(result[0][0]["name"], "$pageview")
        self.assertEqual(result[0][0]["count"], 1)
        self.assertEqual(["Safari", "11"], result[0][0]["breakdown"])
        self.assertEqual(["Safari", "11"], result[0][0]["breakdown_value"])

        self.assertEqual(result[0][1]["name"], "$pageleave")
        self.assertEqual(result[0][1]["count"], 0)
        self.assertEqual(["Safari", "11"], result[0][1]["breakdown"])
        self.assertEqual(["Safari", "11"], result[0][1]["breakdown_value"])

        self.assertEqual(result[1][0]["name"], "$pageview")
        self.assertEqual(result[1][0]["count"], 1)
        self.assertEqual(["Chrome", "95"], result[1][0]["breakdown"])
        self.assertEqual(["Chrome", "95"], result[1][0]["breakdown_value"])

        self.assertEqual(result[1][1]["name"], "$pageleave")
        self.assertEqual(result[1][1]["count"], 1)
        self.assertEqual(["Chrome", "95"], result[1][1]["breakdown"])
        self.assertEqual(["Chrome", "95"], result[1][1]["breakdown_value"])

    @staticmethod
    def as_result(breakdown_properties: Union[str, List[str]]) -> Dict[str, Any]:
        return {
            "action_id": "$pageview",
            "name": "$pageview",
            "custom_name": None,
            "order": 0,
            "people": ["a uuid"],
            "count": 1,
            "type": "events",
            "average_conversion_time": None,
            "median_conversion_time": None,
            "breakdown": breakdown_properties,
            "breakdown_value": breakdown_properties,
        }


def get_converted_and_dropped_people(client: Client, step):
    # Helper for fetching converted/dropped people for a specified funnel step response
    converted_people_response = client.get(step["converted_people_url"])
    assert converted_people_response.status_code == status.HTTP_200_OK

    converted_people = converted_people_response.json()["results"][0]["people"]
    converted_distinct_ids = [distinct_id for people in converted_people for distinct_id in people["distinct_ids"]]

    if step["order"] == 0:
        #  If it's the first step, we don't expect a dropped people url
        dropped_distinct_ids = []
    else:
        dropped_people_response = client.get(step["dropped_people_url"])
        assert dropped_people_response.status_code == status.HTTP_200_OK

        dropped_people = dropped_people_response.json()["results"][0]["people"]
        dropped_distinct_ids = [distinct_id for people in dropped_people for distinct_id in people["distinct_ids"]]

    return {
        "name": step["name"],
        "converted": sorted(converted_distinct_ids),
        "dropped": sorted(dropped_distinct_ids),
    }


def get_funnel_people_breakdown_by_step(client: Client, funnel_response):
    # Helper to fetch converted/dropped people for a non-breakdown funnel response
    return [get_converted_and_dropped_people(client=client, step=step) for step in funnel_response["result"]]


def get_funnel_breakdown_people_breakdown_by_step(client: Client, funnel_response):
    # Helper to fetch converted/dropped people for a breakdown funnel response
    return [
        {
            "breakdown_value": breakdown_steps[0]["breakdown_value"],
            "steps": [get_converted_and_dropped_people(client=client, step=step) for step in breakdown_steps],
        }
        for breakdown_steps in funnel_response["result"]
    ]
