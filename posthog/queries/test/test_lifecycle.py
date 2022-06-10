import json
from unittest.mock import patch

from freezegun import freeze_time
from rest_framework.test import APIRequestFactory

from ee.clickhouse.util import snapshot_clickhouse_queries
from posthog.constants import FILTER_TEST_ACCOUNTS, TRENDS_LIFECYCLE
from posthog.models import Filter
from posthog.test.base import APIBaseTest
from posthog.utils import relative_date_parse


# parameterize tests to reuse in EE
def lifecycle_test_factory(trends, event_factory, person_factory, action_factory):
    class TestLifecycle(APIBaseTest):
        def _create_events(self, data):
            person_result = []
            for id, timestamps in data:
                with freeze_time(timestamps[0]):
                    person_result.append(
                        person_factory(
                            team_id=self.team.pk,
                            distinct_ids=[id],
                            properties={"name": id, **({"email": "test@posthog.com"} if id == "p1" else {})},
                        ),
                    )
                for timestamp in timestamps:
                    event_factory(
                        team=self.team, event="$pageview", distinct_id=id, timestamp=timestamp,
                    )
            return person_result

        def test_lifecycle_trend(self):
            self._create_events(
                data=[
                    (
                        "p1",
                        [
                            "2020-01-11T12:00:00Z",
                            "2020-01-12T12:00:00Z",
                            "2020-01-13T12:00:00Z",
                            "2020-01-15T12:00:00Z",
                            "2020-01-17T12:00:00Z",
                            "2020-01-19T12:00:00Z",
                        ],
                    ),
                    ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
                    ("p3", ["2020-01-12T12:00:00Z"]),
                    ("p4", ["2020-01-15T12:00:00Z"]),
                ]
            )

            result = trends().run(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                    }
                ),
                self.team,
            )

            self.assertLifecycleResults(
                result,
                [
                    {"status": "dormant", "data": [0, -2, -1, 0, -2, 0, -1, 0]},
                    {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                    {"status": "resurrecting", "data": [1, 0, 0, 1, 0, 1, 0, 1]},
                    {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
                ],
            )

        def test_lifecycle_trend_prop_filtering(self):

            p1 = person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-11T12:00:00Z",
                properties={"$number": 1},
            )
            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-12T12:00:00Z",
                properties={"$number": 1},
            )
            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-13T12:00:00Z",
                properties={"$number": 1},
            )

            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-15T12:00:00Z",
                properties={"$number": 1},
            )

            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-17T12:00:00Z",
                properties={"$number": 1},
            )

            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-19T12:00:00Z",
                properties={"$number": 1},
            )

            p2 = person_factory(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-01-09T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-01-12T12:00:00Z",
            )

            p3 = person_factory(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "p3"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p3", timestamp="2020-01-12T12:00:00Z",
            )

            p4 = person_factory(team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "p4"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p4", timestamp="2020-01-15T12:00:00Z",
            )

            result = trends().run(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                        "properties": [{"key": "$number", "value": 1}],
                    }
                ),
                self.team,
            )

            self.assertLifecycleResults(
                result,
                [
                    {"status": "dormant", "data": [0, 0, -1, 0, -1, 0, -1, 0]},
                    {"status": "new", "data": [0, 0, 0, 0, 0, 0, 0, 0]},
                    {"status": "resurrecting", "data": [0, 0, 0, 1, 0, 1, 0, 1]},
                    {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
                ],
            )

        def test_lifecycle_trends_distinct_id_repeat(self):
            with freeze_time("2020-01-12T12:00:00Z"):
                p1 = person_factory(team_id=self.team.pk, distinct_ids=["p1", "another_p1"], properties={"name": "p1"})

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-12T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="another_p1", timestamp="2020-01-14T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-15T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-17T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-19T12:00:00Z",
            )

            result = trends().run(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                    }
                ),
                self.team,
            )

            self.assertLifecycleResults(
                result,
                [
                    {"status": "dormant", "data": [0, -1, 0, 0, -1, 0, -1, 0]},
                    {"status": "new", "data": [1, 0, 0, 0, 0, 0, 0, 0]},
                    {"status": "resurrecting", "data": [0, 0, 1, 0, 0, 1, 0, 1]},
                    {"status": "returning", "data": [0, 0, 0, 1, 0, 0, 0, 0]},
                ],
            )

        def test_lifecycle_trend_people(self):

            people = self._create_events(
                data=[
                    (
                        "p1",
                        [
                            "2020-01-11T12:00:00Z",
                            "2020-01-12T12:00:00Z",
                            "2020-01-13T12:00:00Z",
                            "2020-01-15T12:00:00Z",
                            "2020-01-17T12:00:00Z",
                            "2020-01-19T12:00:00Z",
                        ],
                    ),
                    ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
                    ("p3", ["2020-01-12T12:00:00Z"]),
                    ("p4", ["2020-01-15T12:00:00Z"]),
                ]
            )

            p1 = people[0]
            request_factory = APIRequestFactory()
            request = request_factory.get("/person/lifecycle")

            result = trends().get_people(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                    }
                ),
                self.team,
                relative_date_parse("2020-01-13T00:00:00Z"),
                "returning",
                request,
            )

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["id"], p1.pk)

            dormant_result = trends().get_people(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                    }
                ),
                self.team,
                relative_date_parse("2020-01-13T00:00:00Z"),
                "dormant",
                request,
            )

            self.assertEqual(len(dormant_result), 2)

            dormant_result = trends().get_people(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                    }
                ),
                self.team,
                relative_date_parse("2020-01-14T00:00:00Z"),
                "dormant",
                request,
            )

            self.assertEqual(len(dormant_result), 1)

        def test_lifecycle_trend_people_paginated(self):
            with freeze_time("2020-01-15T12:00:00Z"):
                for i in range(150):
                    person_id = "person{}".format(i)
                    person_factory(team_id=self.team.pk, distinct_ids=[person_id])
                    event_factory(
                        team=self.team, event="$pageview", distinct_id=person_id, timestamp="2020-01-15T12:00:00Z",
                    )
            # even if set to hour 6 it should default to beginning of day and include all pageviews above
            result = self.client.get(
                "/api/person/lifecycle",
                data={
                    "date_from": "2020-01-12T00:00:00Z",
                    "date_to": "2020-01-19T00:00:00Z",
                    "events": json.dumps([{"id": "$pageview", "type": "events", "order": 0}]),
                    "shown_as": TRENDS_LIFECYCLE,
                    "lifecycle_type": "new",
                    "target_date": "2020-01-15T00:00:00Z",
                },
            ).json()
            self.assertEqual(len(result["results"][0]["people"]), 100)

            second_result = self.client.get(result["next"]).json()
            self.assertEqual(len(second_result["results"][0]["people"]), 50)

        def test_lifecycle_trend_action(self):

            self._create_events(
                data=[
                    (
                        "p1",
                        [
                            "2020-01-11T12:00:00Z",
                            "2020-01-12T12:00:00Z",
                            "2020-01-13T12:00:00Z",
                            "2020-01-15T12:00:00Z",
                            "2020-01-17T12:00:00Z",
                            "2020-01-19T12:00:00Z",
                        ],
                    ),
                    ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
                    ("p3", ["2020-01-12T12:00:00Z"]),
                    ("p4", ["2020-01-15T12:00:00Z"]),
                ]
            )

            pageview_action = action_factory(team=self.team, name="$pageview")

            result = trends().run(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "actions": [{"id": pageview_action.pk, "type": "actions", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                    }
                ),
                self.team,
            )

            self.assertLifecycleResults(
                result,
                [
                    {"status": "dormant", "data": [0, -2, -1, 0, -2, 0, -1, 0]},
                    {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                    {"status": "resurrecting", "data": [1, 0, 0, 1, 0, 1, 0, 1]},
                    {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
                ],
            )

        def test_lifecycle_trend_all_time(self):
            self._create_events(
                data=[
                    (
                        "p1",
                        [
                            "2020-01-11T12:00:00Z",
                            "2020-01-12T12:00:00Z",
                            "2020-01-13T12:00:00Z",
                            "2020-01-15T12:00:00Z",
                            "2020-01-17T12:00:00Z",
                            "2020-01-19T12:00:00Z",
                        ],
                    ),
                    ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
                    ("p3", ["2020-01-12T12:00:00Z"]),
                    ("p4", ["2020-01-15T12:00:00Z"]),
                ]
            )

            with freeze_time("2020-01-17T13:01:01Z"):
                result = trends().run(
                    Filter(
                        data={
                            "date_from": "all",
                            "events": [{"id": "$pageview", "type": "events", "order": 0}],
                            "shown_as": TRENDS_LIFECYCLE,
                        }
                    ),
                    self.team,
                )

            self.assertLifecycleResults(
                result,
                [
                    {"status": "dormant", "data": [0, -1, 0, 0, -2, -1, 0, -2, 0]},
                    {"status": "new", "data": [1, 0, 1, 1, 0, 0, 1, 0, 0]},
                    {"status": "returning", "data": [0, 0, 0, 1, 1, 0, 0, 0, 0]},
                    {"status": "resurrecting", "data": [0, 0, 0, 1, 0, 0, 1, 0, 1]},
                ],
            )

        def test_lifecycle_trend_weeks(self):
            # lifecycle weeks rounds the date to the nearest following week  2/5 -> 2/10
            self._create_events(
                data=[
                    (
                        "p1",
                        [
                            "2020-02-01T12:00:00Z",
                            "2020-02-05T12:00:00Z",
                            "2020-02-10T12:00:00Z",
                            "2020-02-15T12:00:00Z",
                            "2020-02-27T12:00:00Z",
                            "2020-03-02T12:00:00Z",
                        ],
                    ),
                    ("p2", ["2020-02-11T12:00:00Z", "2020-02-18T12:00:00Z"]),
                    ("p3", ["2020-02-12T12:00:00Z"]),
                    ("p4", ["2020-02-27T12:00:00Z"]),
                ]
            )

            result = trends().run(
                Filter(
                    data={
                        "date_from": "2020-02-05T00:00:00Z",
                        "date_to": "2020-03-09T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                        "interval": "week",
                    }
                ),
                self.team,
            )

            self.assertEqual(
                result[0]["days"], ["2020-02-03", "2020-02-10", "2020-02-17", "2020-02-24", "2020-03-02", "2020-03-09"]
            )

            self.assertLifecycleResults(
                result,
                [
                    {"status": "dormant", "data": [0, 0, -2, -1, -1, -1]},
                    {"status": "new", "data": [0, 2, 0, 1, 0, 0]},
                    {"status": "resurrecting", "data": [0, 0, 0, 1, 0, 0]},
                    {"status": "returning", "data": [1, 1, 1, 0, 1, 0]},
                ],
            )

        def test_lifecycle_trend_months(self):
            self._create_events(
                data=[
                    (
                        "p1",
                        [
                            "2020-01-11T12:00:00Z",
                            "2020-02-12T12:00:00Z",
                            "2020-03-13T12:00:00Z",
                            "2020-05-15T12:00:00Z",
                            "2020-07-17T12:00:00Z",
                            "2020-09-19T12:00:00Z",
                        ],
                    ),
                    ("p2", ["2019-12-09T12:00:00Z", "2020-02-12T12:00:00Z",]),
                    ("p3", ["2020-02-12T12:00:00Z"]),
                    ("p4", ["2020-05-15T12:00:00Z"]),
                ]
            )

            result = trends().run(
                Filter(
                    data={
                        "date_from": "2020-02-01T00:00:00Z",
                        "date_to": "2020-09-01T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                        "interval": "month",
                    }
                ),
                self.team,
            )

            self.assertLifecycleResults(
                result,
                [
                    {"status": "dormant", "data": [0, -2, -1, 0, -2, 0, -1, 0]},
                    {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                    {"status": "resurrecting", "data": [1, 0, 0, 1, 0, 1, 0, 1]},
                    {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
                ],
            )

        def test_filter_test_accounts(self):
            self._create_events(
                data=[
                    (
                        "p1",  # p1 gets test@posthog.com as email and gets filtered out
                        [
                            "2020-01-11T12:00:00Z",
                            "2020-01-12T12:00:00Z",
                            "2020-01-13T12:00:00Z",
                            "2020-01-15T12:00:00Z",
                            "2020-01-17T12:00:00Z",
                            "2020-01-19T12:00:00Z",
                        ],
                    ),
                    ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
                    ("p3", ["2020-01-12T12:00:00Z"]),
                    ("p4", ["2020-01-15T12:00:00Z"]),
                ]
            )

            result = trends().run(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                        FILTER_TEST_ACCOUNTS: True,
                    },
                    team=self.team,
                ),
                self.team,
            )

            self.assertLifecycleResults(
                result,
                [
                    {"status": "dormant", "data": [0, -2, 0, 0, -1, 0, 0, 0]},
                    {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                    {"status": "resurrecting", "data": [1, 0, 0, 0, 0, 0, 0, 0]},
                    {"status": "returning", "data": [0, 0, 0, 0, 0, 0, 0, 0]},
                ],
            )

            request_factory = APIRequestFactory()
            request = request_factory.get("/person/lifecycle")

            dormant_result = trends().get_people(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                        FILTER_TEST_ACCOUNTS: True,
                    },
                    team=self.team,
                ),
                self.team,
                relative_date_parse("2020-01-13T00:00:00Z"),
                "dormant",
                request,
            )

        def assertLifecycleResults(self, results, expected):
            sorted_results = [
                {"status": r["status"], "data": r["data"]} for r in sorted(results, key=lambda r: r["status"])
            ]
            sorted_expected = list(sorted(expected, key=lambda r: r["status"]))

            self.assertEquals(sorted_results, sorted_expected)

        @snapshot_clickhouse_queries
        @patch("posthoganalytics.feature_enabled", return_value=True)
        def test_timezones(self, patch_something):
            self._create_events(
                data=[
                    (
                        "p1",
                        [
                            "2020-01-11T23:00:00Z",
                            "2020-01-12T01:00:00Z",
                            "2020-01-13T12:00:00Z",
                            "2020-01-15T12:00:00Z",
                            "2020-01-17T12:00:00Z",
                            "2020-01-19T12:00:00Z",
                        ],
                    ),
                    ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
                    ("p3", ["2020-01-12T12:00:00Z"]),
                    ("p4", ["2020-01-15T12:00:00Z"]),
                ]
            )

            result = trends().run(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                    }
                ),
                self.team,
            )

            self.assertLifecycleResults(
                result,
                [
                    {"status": "dormant", "data": [0, -2, -1, 0, -2, 0, -1, 0]},
                    {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                    {"status": "resurrecting", "data": [1, 0, 0, 1, 0, 1, 0, 1]},
                    {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
                ],
            )

            self.team.timezone = "US/Pacific"
            self.team.save()

            result_pacific = trends().run(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                    },
                    team=self.team,
                ),
                self.team,
            )
            self.assertLifecycleResults(
                result_pacific,
                [
                    {"status": "dormant", "data": [-1.0, -2.0, -1.0, 0.0, -2.0, 0.0, -1.0, 0.0]},
                    {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                    {"status": "resurrecting", "data": [1, 1, 0, 1, 0, 1, 0, 1]},
                    {"status": "returning", "data": [0, 0, 0, 0, 0, 0, 0, 0]},
                ],
            )

    return TestLifecycle
