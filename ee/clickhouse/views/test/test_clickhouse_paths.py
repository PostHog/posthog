import json

from rest_framework import status

from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import FUNNEL_PATH_AFTER_STEP, INSIGHT_FUNNELS, INSIGHT_PATHS
from posthog.test.base import APIBaseTest, _create_event, _create_person


class TestClickhousePaths(ClickhouseTestMixin, APIBaseTest):
    def _create_sample_data(self, num, delete=False):
        for i in range(num):
            person = _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(
                event="step one",
                distinct_id=f"user_{i}",
                team=self.team,
                timestamp="2021-05-01 00:00:00",
                properties={"$browser": "Chrome"},
            )
            if i % 2 == 0:
                _create_event(
                    event="step two",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:10:00",
                    properties={"$browser": "Chrome"},
                )
            _create_event(
                event="step three",
                distinct_id=f"user_{i}",
                team=self.team,
                timestamp="2021-05-01 00:20:00",
                properties={"$browser": "Chrome"},
            )
            if delete:
                person.delete()

    def test_insight_paths_basic(self):
        _create_person(team=self.team, distinct_ids=["person_1"])
        _create_event(
            properties={"$current_url": "/"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about"}, distinct_id="person_1", event="$pageview", team=self.team,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/insights/path",).json()
        self.assertEqual(len(response["result"]), 1)

    def test_insight_paths_basic_exclusions(self):
        _create_person(team=self.team, distinct_ids=["person_1"])
        _create_event(
            distinct_id="person_1", event="first event", team=self.team,
        )
        _create_event(
            distinct_id="person_1", event="second event", team=self.team,
        )
        _create_event(
            distinct_id="person_1", event="third event", team=self.team,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/path", data={"exclude_events": '["second event"]'}
        ).json()
        self.assertEqual(len(response["result"]), 1)

    def test_backwards_compatible_path_types(self):

        _create_person(team=self.team, distinct_ids=["person_1"])
        _create_event(
            properties={"$current_url": "/"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/something else"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$screen_name": "/screen1"}, distinct_id="person_1", event="$screen", team=self.team,
        )
        _create_event(
            distinct_id="person_1", event="custom1", team=self.team,
        )
        _create_event(
            distinct_id="person_1", event="custom2", team=self.team,
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/path", data={"path_type": "$pageview", "insight": "PATHS",}
        ).json()
        self.assertEqual(len(response["result"]), 2)

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/path", data={"path_type": "custom_event", "insight": "PATHS"}
        ).json()
        self.assertEqual(len(response["result"]), 1)
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/path", data={"path_type": "$screen", "insight": "PATHS"}
        ).json()
        self.assertEqual(len(response["result"]), 0)

    def test_backwards_compatible_start_point(self):

        _create_person(team=self.team, distinct_ids=["person_1"])
        _create_event(
            properties={"$current_url": "/"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/something else"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$screen_name": "/screen1"}, distinct_id="person_1", event="$screen", team=self.team,
        )
        _create_event(
            properties={"$screen_name": "/screen2"}, distinct_id="person_1", event="$screen", team=self.team,
        )
        _create_event(
            distinct_id="person_1", event="custom1", team=self.team,
        )
        _create_event(
            distinct_id="person_1", event="custom2", team=self.team,
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/path",
            data={"path_type": "$pageview", "insight": "PATHS", "start_point": "/about",},
        ).json()
        self.assertEqual(len(response["result"]), 1)

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/path",
            data={"path_type": "custom_event", "insight": "PATHS", "start_point": "custom2",},
        ).json()
        self.assertEqual(len(response["result"]), 0)
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/path",
            data={"path_type": "$screen", "insight": "PATHS", "start_point": "/screen1",},
        ).json()
        self.assertEqual(len(response["result"]), 1)

    def test_path_groupings(self):
        _create_person(team=self.team, distinct_ids=["person_1"])
        _create_event(
            properties={"$current_url": "/about_1"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about_2"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/something else"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about3"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about4"}, distinct_id="person_1", event="$pageview", team=self.team,
        )

        _create_person(team=self.team, distinct_ids=["person_2"])
        _create_event(
            properties={"$current_url": "/about_1"}, distinct_id="person_2", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about_2"}, distinct_id="person_2", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/something else"}, distinct_id="person_2", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about3"}, distinct_id="person_2", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about4"}, distinct_id="person_2", event="$pageview", team=self.team,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/path",
            data={"insight": "PATHS", "path_groupings": json.dumps(["/about*"])},
        ).json()
        self.assertEqual(len(response["result"]), 2)

        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/path",
            data={"insight": "PATHS", "path_groupings": json.dumps(["/about_*"])},
        ).json()
        self.assertEqual(len(response["result"]), 3)

    def test_funnel_path_post(self):
        self._create_sample_data(7)
        request_data = {
            "insight": INSIGHT_PATHS,
            "funnel_paths": FUNNEL_PATH_AFTER_STEP,
            "filter_test_accounts": "false",
            "date_from": "2021-05-01",
            "date_to": "2021-05-07",
        }

        funnel_filter = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 7,
            "funnel_window_interval_unit": "day",
            "funnel_step": 2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        post_response = self.client.post(
            f"/api/projects/{self.team.id}/insights/path/", data={**request_data, "funnel_filter": funnel_filter}
        )
        self.assertEqual(post_response.status_code, status.HTTP_200_OK)
        post_j = post_response.json()
        self.assertEqual(
            post_j["result"],
            [{"source": "1_step two", "target": "2_step three", "value": 4, "average_conversion_time": 600000.0}],
        )
