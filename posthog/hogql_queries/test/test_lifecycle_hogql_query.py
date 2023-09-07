from datetime import datetime

from freezegun import freeze_time

from posthog.hogql.query import execute_hogql_query
from posthog.models.utils import UUIDT
from posthog.hogql_queries.lifecycle_hogql_query import create_events_query, create_time_filter
from posthog.hogql_queries.query_date_range import QueryDateRange
from posthog.schema import DateRange, IntervalType
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events


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

    def run_events_query(self, date_from, date_to, interval):
        date_range = QueryDateRange(
            date_range=DateRange(date_from=date_from, date_to=date_to),
            team=self.team,
            interval=interval,
            now=datetime.strptime("2020-01-30T00:00:00Z", "%Y-%m-%dT%H:%M:%SZ"),
        )
        time_filter = create_time_filter(date_range)

        # TODO probably doesn't make sense to test like this
        #  maybe this query should be what is returned by the function
        events_query = create_events_query(event_filter=time_filter, date_range=date_range)
        return execute_hogql_query(
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

    def test_events_query_whole_range(self):
        self._create_test_events()

        date_from = "2020-01-09"
        date_to = "2020-01-19"

        response = self.run_events_query(date_from, date_to, IntervalType.day)

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
        response = self.run_events_query(date_from, date_to, IntervalType.day)

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

    # def test_start_on_dormant(self):
    #     self.create_test_events()
    #     date_from = "2020-01-13"
    #     date_to = "2020-01-14"
    #     response = self.run_events_query(date_from, date_to, IntervalType.day)
    #
    #     self.assertEqual(
    #         {
    #             (datetime(2020, 1, 12, 0, 0), 1, "new"),  # p3
    #             # TODO this currently fails, as it treats p1 as resurrecting.
    #             # This might just be fine, later in the query we would just throw away results before the 13th
    #             (datetime(2020, 1, 12, 0, 0), 1, "resurrecting"),  # p2
    #             (datetime(2020, 1, 12, 0, 0), 1, "returning"),  # p1
    #             (datetime(2020, 1, 13, 0, 0), 1, "returning"),  # p1
    #             (datetime(2020, 1, 13, 0, 0), 2, "dormant"),  # p2, p3
    #             (datetime(2020, 1, 14, 0, 0), 1, "dormant"),  # p1
    #         },
    #         set(response.results),
    #     )
