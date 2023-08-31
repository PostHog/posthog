from datetime import datetime

from freezegun import freeze_time

from posthog.models.utils import UUIDT
from posthog.nodes.lifecycle_hogql_query import run_lifecycle_query, create_events_query, create_time_filter
from posthog.nodes.query_date_range import QueryDateRange
from posthog.schema import LifecycleQuery, DateRange, IntervalType
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from posthog.hogql.query import execute_hogql_query


class TestQuery(ClickhouseTestMixin, APIBaseTest):
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
                properties={"random_prop": "don't include", "random_uuid": random_uuid, "index": index},
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
                        properties={"name": id, **({"email": "test@posthog.com"} if id == "p1" else {})},
                    )
                )
            for timestamp in timestamps:
                _create_event(team=self.team, event=event, distinct_id=id, timestamp=timestamp)
        return person_result

    def test_query(self):
        with freeze_time("2023-08-10"):
            self._create_random_events()
            response = run_lifecycle_query(
                query=LifecycleQuery.parse_obj(
                    {
                        "kind": "LifecycleQuery",
                        "dateRange": {"date_from": "-7d"},
                        "series": [{"kind": "EventsNode", "event": "$pageview", "name": "$pageview", "math": "total"}],
                        "lifecycleFilter": {"shown_as": "Lifecycle"},
                        "interval": "day",
                    }
                ),
                team=self.team,
            )
            self.assertEqual(
                response,
                [
                    [
                        {
                            "data": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                            "count": 0.0,
                            "labels": [
                                "2-Aug-2023",
                                "3-Aug-2023",
                                "4-Aug-2023",
                                "5-Aug-2023",
                                "6-Aug-2023",
                                "7-Aug-2023",
                                "8-Aug-2023",
                                "9-Aug-2023",
                            ],
                            "days": [
                                "2023-08-02",
                                "2023-08-03",
                                "2023-08-04",
                                "2023-08-05",
                                "2023-08-06",
                                "2023-08-07",
                                "2023-08-08",
                                "2023-08-09",
                            ],
                            "label": " - new",
                            "status": "new",
                        },
                        {
                            "data": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                            "count": 0.0,
                            "labels": [
                                "2-Aug-2023",
                                "3-Aug-2023",
                                "4-Aug-2023",
                                "5-Aug-2023",
                                "6-Aug-2023",
                                "7-Aug-2023",
                                "8-Aug-2023",
                                "9-Aug-2023",
                            ],
                            "days": [
                                "2023-08-02",
                                "2023-08-03",
                                "2023-08-04",
                                "2023-08-05",
                                "2023-08-06",
                                "2023-08-07",
                                "2023-08-08",
                                "2023-08-09",
                            ],
                            "label": " - dormant",
                            "status": "dormant",
                        },
                        {
                            "data": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                            "count": 0.0,
                            "labels": [
                                "2-Aug-2023",
                                "3-Aug-2023",
                                "4-Aug-2023",
                                "5-Aug-2023",
                                "6-Aug-2023",
                                "7-Aug-2023",
                                "8-Aug-2023",
                                "9-Aug-2023",
                            ],
                            "days": [
                                "2023-08-02",
                                "2023-08-03",
                                "2023-08-04",
                                "2023-08-05",
                                "2023-08-06",
                                "2023-08-07",
                                "2023-08-08",
                                "2023-08-09",
                            ],
                            "label": " - resurrecting",
                            "status": "resurrecting",
                        },
                        {
                            "data": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                            "count": 0.0,
                            "labels": [
                                "2-Aug-2023",
                                "3-Aug-2023",
                                "4-Aug-2023",
                                "5-Aug-2023",
                                "6-Aug-2023",
                                "7-Aug-2023",
                                "8-Aug-2023",
                                "9-Aug-2023",
                            ],
                            "days": [
                                "2023-08-02",
                                "2023-08-03",
                                "2023-08-04",
                                "2023-08-05",
                                "2023-08-06",
                                "2023-08-07",
                                "2023-08-08",
                                "2023-08-09",
                            ],
                            "label": " - returning",
                            "status": "returning",
                        },
                    ]
                ],
            )

    def test_events_query(self):
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

        date_from = "2020-01-09"
        date_to = "2020-01-19"
        date_range = QueryDateRange(
            date_range=DateRange(date_from=date_from, date_to=date_to),
            team=self.team,
            interval=IntervalType.day,
            now=datetime.strptime("2020-01-30T00:00:00Z", "%Y-%m-%dT%H:%M:%SZ"),
        )
        (time_filter, _, _) = create_time_filter(date_range, interval="day")

        self._create_random_events()
        events_query = create_events_query("day", event_filter=time_filter)
        response = execute_hogql_query(
            team=self.team,
            query="""
            SELECT
            start_of_period, count(DISTINCT person_id) AS counts, status
            FROM {events_query}
            GROUP BY start_of_period, status
            """,
            query_type="LifecycleQuery",
            placeholders={"events_query": events_query},
        )

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
            },
            set(response.results),
        )
