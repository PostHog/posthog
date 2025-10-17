from datetime import datetime
from typing import Any, Union

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries

from posthog.test.test_journeys import journeys_for


class ClickhouseTestFunnelTypes(ClickhouseTestMixin, APIBaseTest):
    def test_funnel_unordered_basic_post(self):
        journeys_for(
            {
                "1": [{"event": "step one"}, {"event": "step two"}],
                "2": [{"event": "step one"}, {"event": "step two"}],
            },
            self.team,
        )

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
        self.assertEqual(response["result"][0]["name"], "Completed 1 step")
        self.assertEqual(response["result"][1]["name"], "Completed 2 steps")
        self.assertEqual(response["result"][0]["count"], 2)
        self.assertEqual(response["result"][1]["count"], 2)

    def test_funnel_strict_basic_post(self):
        journeys_for(
            {
                "1": [{"event": "step one"}, {"event": "step two"}],
                "2": [{"event": "step one"}, {"event": "blahh"}, {"event": "step two"}],
            },
            self.team,
        )

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
        journeys_for(
            {
                "user_one": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 1)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 3)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 5)},
                ],
                "user_two": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 2)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 4)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 5)},
                ],
            },
            self.team,
        )

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
        journeys_for(
            {
                "user_one": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 1)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 3)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 5)},
                ],
                "user_two": [
                    {"event": "step three", "timestamp": datetime(2021, 5, 2)},
                    {"event": "step one", "timestamp": datetime(2021, 5, 4)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 5)},
                ],
            },
            self.team,
        )

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
        journeys_for(
            {
                "user_one": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 1)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 3)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 5)},
                ],
                "user_two": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 2)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 4)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 5)},
                ],
            },
            self.team,
        )

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
        journeys_for(
            {
                "user_one": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 1)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 3)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 5)},
                ],
                "user_two": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 2)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 4)},
                    {"event": "blah", "timestamp": datetime(2021, 5, 4, 2)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 5)},
                ],
                "user_three": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 2)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 4)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 5)},
                ],
            },
            self.team,
        )

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

    @snapshot_clickhouse_queries
    def test_funnel_time_to_convert_auto_bins(self):
        journeys_for(
            {
                "user a": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 8, 18)},
                    {"event": "blah", "timestamp": datetime(2021, 6, 8, 18, 30)},
                    {"event": "step two", "timestamp": datetime(2021, 6, 8, 19)},
                    # Converted from 0 to 1 in 3600 s
                    {"event": "step three", "timestamp": datetime(2021, 6, 8, 21)},
                ],
                "user b": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 9, 13)},
                    {"event": "step two", "timestamp": datetime(2021, 6, 9, 13, 37)},
                    # Converted from 0 to 1 in 2200 s
                ],
                "user c": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 11, 7)},
                    {"event": "step two", "timestamp": datetime(2021, 6, 12, 6)},
                    # Converted from 0 to 1 in 82_800 s
                ],
            },
            self.team,
        )

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
            response_data
            | {
                "is_cached": False,
                "timezone": "UTC",
                "result": {
                    "bins": [[2220, 2], [42510, 0], [82800, 1]],
                    "average_conversion_time": 29540,
                },
            },
        )

    @snapshot_clickhouse_queries
    def test_funnel_time_to_convert_auto_bins_strict(self):
        journeys_for(
            {
                "user a": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 8, 18)},
                    {"event": "step two", "timestamp": datetime(2021, 6, 8, 19)},
                    # Converted from 0 to 1 in 3600 s
                    {"event": "step three", "timestamp": datetime(2021, 6, 8, 21)},
                ],
                "user b": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 9, 13)},
                    {"event": "step two", "timestamp": datetime(2021, 6, 9, 13, 37)},
                    # Converted from 0 to 1 in 2200 s
                ],
                "user c": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 11, 7)},
                    {"event": "step two", "timestamp": datetime(2021, 6, 12, 6)},
                    # Converted from 0 to 1 in 82_800 s
                ],
            },
            self.team,
        )

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
            response_data
            | {
                "is_cached": False,
                "timezone": "UTC",
                "result": {
                    "bins": [[2220.0, 2], [42510.0, 0], [82800.0, 1]],
                    "average_conversion_time": 29540.0,
                },
            },
        )

    @snapshot_clickhouse_queries
    def test_funnel_time_to_convert_auto_bins_unordered(self):
        journeys_for(
            {
                "user a": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 8, 18)},
                    {"event": "step two", "timestamp": datetime(2021, 6, 8, 19)},
                    # Converted from 0 to 1 in 3600 s
                    {"event": "step three", "timestamp": datetime(2021, 6, 8, 21)},
                ],
                "user b": [
                    {"event": "step two", "timestamp": datetime(2021, 6, 9, 13)},
                    {"event": "step one", "timestamp": datetime(2021, 6, 9, 13, 37)},
                    # Converted from 0 to 1 in 2200 s
                ],
                "user c": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 11, 7)},
                    {"event": "step two", "timestamp": datetime(2021, 6, 12, 6)},
                    # Converted from 0 to 1 in 82_800 s
                ],
            },
            self.team,
        )

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
            response_data
            | {
                "is_cached": False,
                "timezone": "UTC",
                "result": {
                    "bins": [[2220.0, 2], [42510.0, 0], [82800.0, 1]],
                    "average_conversion_time": 29540.0,
                },
            },
        )

    def test_funnel_invalid_action_handled(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel/",
            {"actions": [{"id": 666, "type": "actions", "order": 0}, {"id": 666, "type": "actions", "order": 0}]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            self.validation_error_response("Action ID 666 does not exist!"),
        )

    def test_funnel_basic_exclusions(self):
        journeys_for(
            {
                "1": [
                    {"event": "step one"},
                    {"event": "step x"},
                    {"event": "step two"},
                ],
                "2": [{"event": "step one"}, {"event": "step two"}],
            },
            self.team,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel/",
            {
                "events": [
                    {"id": "step one", "type": "events", "order": 0},
                    {"id": "step two", "type": "events", "order": 1},
                ],
                "exclusions": [
                    {
                        "id": "step x",
                        "type": "events",
                        "funnel_from_step": 0,
                        "funnel_to_step": 1,
                    }
                ],
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
        journeys_for(
            {
                "1": [
                    {"event": "step one"},
                    {"event": "step x"},
                    {"event": "step two"},
                ],
                "2": [{"event": "step one"}, {"event": "step two"}],
            },
            self.team,
        )

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
                        }
                    ],
                    "funnel_window_days": 14,
                    "insight": "funnels",
                },
            )

            if error:
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json(),
                    self.validation_error_response(
                        "Exclusion steps cannot contain an event that's part of funnel steps."
                    ),
                )
            else:
                self.assertEqual(response.status_code, 200)

    def test_single_property_breakdown(self):
        journeys_for(
            {
                "person1": [
                    {
                        "event": "$pageview",
                        "properties": {"$browser": "Chrome", "$browser_version": 95},
                    },
                    {
                        "event": "$pageleave",
                        "properties": {"$browser": "Chrome", "$browser_version": 95},
                    },
                ],
                "person2": [
                    {
                        "event": "$pageview",
                        "properties": {"$browser": "Safari", "$browser_version": 11},
                    },
                    {
                        "event": "$pageview",
                        "properties": {"$browser": "Safari", "$browser_version": 11},
                    },
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
                {
                    "id": "$pageleave",
                    "name": "$pageleave",
                    "type": "events",
                    "order": 1,
                },
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

        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/funnel?refresh=true",
            filter_with_breakdown,
        )
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

    @staticmethod
    def as_result(breakdown_properties: Union[str, list[str]]) -> dict[str, Any]:
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
