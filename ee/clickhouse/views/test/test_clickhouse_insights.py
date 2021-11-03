import json
from typing import Any, Dict, List, Union
from unittest.mock import patch
from uuid import uuid4

from rest_framework import status

from ee.api.test.base import LicensedTestMixin
from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from ee.models.explicit_team_membership import ExplicitTeamMembership
from posthog.api.test.test_insight import insight_test_factory
from posthog.models.organization import OrganizationMembership
from posthog.models.person import Person
from posthog.test.base import APIBaseTest


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid)


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

    @patch("ee.clickhouse.views.insights.ClickhouseInsightsViewSet.calculate_funnel")
    def test_that_multi_property_breakdown_is_not_breaking(self, mcf):

        test_cases: List[Dict[str, Any]] = [
            # single property
            {"breakdown": "$browser", "funnel result": ["Chrome", "Safari"], "expected": ["Chrome", "Safari"]},
            # single property client, multi property query result
            {"breakdown": "$browser", "funnel result": [["Chrome"], ["Safari"]], "expected": ["Chrome", "Safari"]},
            # multi property client, multi property query result
            {
                "breakdown": ["$browser"],
                "funnel result": [["Chrome"], ["Safari"]],
                "expected": [["Chrome"], ["Safari"]],
            },
        ]

        for test_case in test_cases:

            filter_with_breakdown = {
                "insight": "FUNNELS",
                "date_from": "-14d",
                "actions": [],
                "events": [
                    {"id": "$pageview", "name": "$pageview", "type": "events", "order": 0},
                    {"id": "$pageview", "type": "events", "order": 1, "name": "$pageview"},
                ],
                "display": "FunnelViz",
                "interval": "day",
                "properties": [],
                "funnel_viz_type": "steps",
                "exclusions": [],
                "breakdown": test_case["breakdown"],
                "breakdown_type": "event",
                "funnel_from_step": 0,
                "funnel_to_step": 1,
            }

            mcf.return_value = {"result": [[self.as_result(b), self.as_result(b)] for b in test_case["funnel result"]]}

            response = self.client.post(f"/api/projects/{self.team.id}/insights/funnel", filter_with_breakdown)
            self.assertEqual(200, response.status_code)

            response_data = response.json()

            result = response_data["result"]

            # input events have chrome and safari so results is an array with two arrays as its contents
            for i in range(0, 2):
                for funnel_data in result[i]:
                    self.assertIsInstance(funnel_data["name"], str)
                    self.assertEqual(test_case["expected"][i], funnel_data["breakdown"])
                    self.assertEqual(test_case["expected"][i], funnel_data["breakdown_value"])

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
