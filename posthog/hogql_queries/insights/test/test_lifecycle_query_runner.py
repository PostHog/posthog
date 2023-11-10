from datetime import datetime

from freezegun import freeze_time

from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.lifecycle_query_runner import LifecycleQueryRunner
from posthog.models.utils import UUIDT
from posthog.schema import DateRange, IntervalType, LifecycleQuery, EventsNode
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
)


class TestLifecycleQueryRunner(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_random_events(self) -> str:
        random_uuid = str(UUIDT())
        _create_person(
            properties={"sneaky_mail": "tim@posthog.com", "random_uuid": random_uuid},
            team=self.team,
            distinct_ids=["bla"],
            is_identified=True,
        )
        flush_persons_and_events()
        for index in range(2):
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={
                    "random_prop": "don't include",
                    "random_uuid": random_uuid,
                    "index": index,
                },
            )
        flush_persons_and_events()
        return random_uuid

    def _create_events(self, data, event="$pageview"):
        person_result = []
        for id, timestamps in data:
            with freeze_time(timestamps[0]):
                person_result.append(
                    _create_person(
                        team_id=self.team.pk,
                        distinct_ids=[id],
                        properties={
                            "name": id,
                            **({"email": "test@posthog.com"} if id == "p1" else {}),
                        },
                    )
                )
            for timestamp in timestamps:
                _create_event(team=self.team, event=event, distinct_id=id, timestamp=timestamp)
        return person_result

    def _create_test_events(self):
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

    def _create_query_runner(self, date_from, date_to, interval) -> LifecycleQueryRunner:
        series = [EventsNode(event="$pageview")]
        query = LifecycleQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            interval=interval,
            series=series,
        )
        return LifecycleQueryRunner(team=self.team, query=query)

    def _run_events_query(self, date_from, date_to, interval):
        events_query = self._create_query_runner(date_from, date_to, interval).events_query
        return execute_hogql_query(
            team=self.team,
            query="""
                SELECT
                start_of_period, count(DISTINCT person_id) AS counts, status
                FROM {events_query}
                GROUP BY start_of_period, status
            """,
            placeholders={"events_query": events_query},
            query_type="LifecycleEventsQuery",
        )

    def _run_lifecycle_query(self, date_from, date_to, interval):
        return self._create_query_runner(date_from, date_to, interval).calculate()

    def test_lifecycle_query_whole_range(self):
        self._create_test_events()

        date_from = "2020-01-09"
        date_to = "2020-01-19"

        response = self._run_lifecycle_query(date_from, date_to, IntervalType.day)

        statuses = [res["status"] for res in response.results]
        self.assertEqual(["new", "returning", "resurrecting", "dormant"], statuses)

        self.assertEqual(
            [
                {
                    "count": 4.0,
                    "data": [
                        1.0,  # 9th, p2
                        0.0,
                        1.0,  # 11th, p1
                        1.0,  # 12th, p3
                        0.0,
                        0.0,
                        1.0,  # 15th, p4
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                    ],
                    "days": [
                        "2020-01-09",
                        "2020-01-10",
                        "2020-01-11",
                        "2020-01-12",
                        "2020-01-13",
                        "2020-01-14",
                        "2020-01-15",
                        "2020-01-16",
                        "2020-01-17",
                        "2020-01-18",
                        "2020-01-19",
                    ],
                    "label": " - new",
                    "labels": [
                        "9-Jan-2020",
                        "10-Jan-2020",
                        "11-Jan-2020",
                        "12-Jan-2020",
                        "13-Jan-2020",
                        "14-Jan-2020",
                        "15-Jan-2020",
                        "16-Jan-2020",
                        "17-Jan-2020",
                        "18-Jan-2020",
                        "19-Jan-2020",
                    ],
                    "status": "new",
                },
                {
                    "count": 2.0,
                    "data": [
                        0.0,  # 9th
                        0.0,  # 10th
                        0.0,  # 11th
                        1.0,  # 12th, p1
                        1.0,  # 13th, p1
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                    ],
                    "days": [
                        "2020-01-09",
                        "2020-01-10",
                        "2020-01-11",
                        "2020-01-12",
                        "2020-01-13",
                        "2020-01-14",
                        "2020-01-15",
                        "2020-01-16",
                        "2020-01-17",
                        "2020-01-18",
                        "2020-01-19",
                    ],
                    "label": " - returning",
                    "labels": [
                        "9-Jan-2020",
                        "10-Jan-2020",
                        "11-Jan-2020",
                        "12-Jan-2020",
                        "13-Jan-2020",
                        "14-Jan-2020",
                        "15-Jan-2020",
                        "16-Jan-2020",
                        "17-Jan-2020",
                        "18-Jan-2020",
                        "19-Jan-2020",
                    ],
                    "status": "returning",
                },
                {
                    "count": 4.0,
                    "data": [
                        0.0,
                        0.0,
                        0.0,
                        1.0,  # 12th, p2
                        0.0,
                        0.0,
                        1.0,  # 15th, p1
                        0.0,
                        1.0,  # 17th, p1
                        0.0,
                        1.0,  # 19th, p1
                    ],
                    "days": [
                        "2020-01-09",
                        "2020-01-10",
                        "2020-01-11",
                        "2020-01-12",
                        "2020-01-13",
                        "2020-01-14",
                        "2020-01-15",
                        "2020-01-16",
                        "2020-01-17",
                        "2020-01-18",
                        "2020-01-19",
                    ],
                    "label": " - resurrecting",
                    "labels": [
                        "9-Jan-2020",
                        "10-Jan-2020",
                        "11-Jan-2020",
                        "12-Jan-2020",
                        "13-Jan-2020",
                        "14-Jan-2020",
                        "15-Jan-2020",
                        "16-Jan-2020",
                        "17-Jan-2020",
                        "18-Jan-2020",
                        "19-Jan-2020",
                    ],
                    "status": "resurrecting",
                },
                {
                    "count": -7.0,
                    "data": [
                        0.0,
                        -1.0,  # 10th, p2
                        0.0,
                        0.0,
                        -2.0,  # 13th, p2, p3
                        -1.0,  # 14th, p1
                        0.0,
                        -2.0,  # 16th, p1, p4
                        0.0,
                        -1.0,  # 18th, p1
                        0.0,
                    ],
                    "days": [
                        "2020-01-09",
                        "2020-01-10",
                        "2020-01-11",
                        "2020-01-12",
                        "2020-01-13",
                        "2020-01-14",
                        "2020-01-15",
                        "2020-01-16",
                        "2020-01-17",
                        "2020-01-18",
                        "2020-01-19",
                    ],
                    "label": " - dormant",
                    "labels": [
                        "9-Jan-2020",
                        "10-Jan-2020",
                        "11-Jan-2020",
                        "12-Jan-2020",
                        "13-Jan-2020",
                        "14-Jan-2020",
                        "15-Jan-2020",
                        "16-Jan-2020",
                        "17-Jan-2020",
                        "18-Jan-2020",
                        "19-Jan-2020",
                    ],
                    "status": "dormant",
                },
            ],
            response.results,
        )

    def test_events_query_whole_range(self):
        self._create_test_events()

        date_from = "2020-01-09"
        date_to = "2020-01-19"

        response = self._run_events_query(date_from, date_to, IntervalType.day)

        self.assertEqual(
            {
                (datetime(2020, 1, 9, 0, 0), 1, "new"),  # p2
                (datetime(2020, 1, 10, 0, 0), 1, "dormant"),  # p2
                (datetime(2020, 1, 11, 0, 0), 1, "new"),  # p1
                (datetime(2020, 1, 12, 0, 0), 1, "new"),  # p3
                (datetime(2020, 1, 12, 0, 0), 1, "resurrecting"),  # p2
                (datetime(2020, 1, 12, 0, 0), 1, "returning"),  # p1
                (datetime(2020, 1, 13, 0, 0), 1, "returning"),  # p1
                (datetime(2020, 1, 13, 0, 0), 2, "dormant"),  # p2, p3
                (datetime(2020, 1, 14, 0, 0), 1, "dormant"),  # p1
                (datetime(2020, 1, 15, 0, 0), 1, "resurrecting"),  # p1
                (datetime(2020, 1, 15, 0, 0), 1, "new"),  # p4
                (datetime(2020, 1, 16, 0, 0), 2, "dormant"),  # p1, p4
                (datetime(2020, 1, 17, 0, 0), 1, "resurrecting"),  # p1
                (datetime(2020, 1, 18, 0, 0), 1, "dormant"),  # p1
                (datetime(2020, 1, 19, 0, 0), 1, "resurrecting"),  # p1
                (datetime(2020, 1, 20, 0, 0), 1, "dormant"),  # p1
            },
            set(response.results),
        )

    def test_events_query_partial_range(self):
        self._create_test_events()
        date_from = "2020-01-12"
        date_to = "2020-01-14"
        response = self._run_events_query(date_from, date_to, IntervalType.day)

        self.assertEqual(
            {
                (datetime(2020, 1, 11, 0, 0), 1, "new"),  # p1
                (datetime(2020, 1, 12, 0, 0), 1, "new"),  # p3
                (datetime(2020, 1, 12, 0, 0), 1, "resurrecting"),  # p2
                (datetime(2020, 1, 12, 0, 0), 1, "returning"),  # p1
                (datetime(2020, 1, 13, 0, 0), 1, "returning"),  # p1
                (datetime(2020, 1, 13, 0, 0), 2, "dormant"),  # p2, p3
                (datetime(2020, 1, 14, 0, 0), 1, "dormant"),  # p1
            },
            set(response.results),
        )
