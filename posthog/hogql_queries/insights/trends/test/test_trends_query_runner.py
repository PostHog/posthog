from dataclasses import dataclass
from typing import List, Optional
from freezegun import freeze_time
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner

from posthog.schema import (
    DateRange,
    EventsNode,
    IntervalType,
    TrendsFilter,
    TrendsQuery,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
)


@dataclass
class Series:
    event: str
    timestamps: List[str]


@dataclass
class SeriesTestData:
    distinct_id: str
    events: List[Series]


class TestQuery(ClickhouseTestMixin, APIBaseTest):
    default_date_from = "2020-01-09"
    default_date_to = "2020-01-19"

    def _create_events(self, data: List[SeriesTestData]):
        person_result = []
        for person in data:
            first_timestamp = person.events[0].timestamps[0]

            with freeze_time(first_timestamp):
                person_result.append(
                    _create_person(
                        team_id=self.team.pk,
                        distinct_ids=[person.distinct_id],
                        properties={
                            "name": person.distinct_id,
                            **({"email": "test@posthog.com"} if person.distinct_id == "p1" else {}),
                        },
                    )
                )
            for event in person.events:
                for timestamp in event.timestamps:
                    _create_event(
                        team=self.team,
                        event=event.event,
                        distinct_id=id,
                        timestamp=timestamp,
                    )
        return person_result

    def _create_test_events(self):
        self._create_events(
            [
                SeriesTestData(
                    distinct_id="p1",
                    events=[
                        Series(
                            event="$pageview",
                            timestamps=[
                                "2020-01-11T12:00:00Z",
                                "2020-01-12T12:00:00Z",
                                "2020-01-13T12:00:00Z",
                                "2020-01-15T12:00:00Z",
                                "2020-01-17T12:00:00Z",
                                "2020-01-19T12:00:00Z",
                            ],
                        ),
                        Series(
                            event="$pageleave",
                            timestamps=[
                                "2020-01-11T12:00:00Z",
                                "2020-01-12T12:00:00Z",
                                "2020-01-13T12:00:00Z",
                            ],
                        ),
                    ],
                ),
                SeriesTestData(
                    distinct_id="p2",
                    events=[
                        Series(
                            event="$pageview",
                            timestamps=["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"],
                        ),
                        Series(
                            event="$pageleave",
                            timestamps=[
                                "2020-01-13T12:00:00Z",
                            ],
                        ),
                    ],
                ),
                SeriesTestData(
                    distinct_id="p3",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-12T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-13T12:00:00Z"]),
                    ],
                ),
                SeriesTestData(
                    distinct_id="p4",
                    events=[
                        Series(event="$pageview", timestamps=["2020-01-15T12:00:00Z"]),
                        Series(event="$pageleave", timestamps=["2020-01-16T12:00:00Z"]),
                    ],
                ),
            ]
        )

    def _create_query_runner(self, date_from, date_to, interval, series, trends_filters) -> TrendsQueryRunner:
        query_series = [EventsNode(event="$pageview")] if series is None else series
        query = TrendsQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            interval=interval,
            series=query_series,
            trendsFilter=trends_filters,
        )
        return TrendsQueryRunner(team=self.team, query=query)

    def _run_trends_query(
        self,
        date_from,
        date_to,
        interval,
        series=None,
        trends_filters: Optional[TrendsFilter] = None,
    ):
        return self._create_query_runner(date_from, date_to, interval, series, trends_filters).calculate()

    def test_trends_query_label(self):
        self._create_test_events()

        response = self._run_trends_query(self.default_date_from, self.default_date_to, IntervalType.day)

        self.assertEqual("$pageview", response.results[0]["label"])

    def test_trends_query_count(self):
        self._create_test_events()

        response = self._run_trends_query(self.default_date_from, self.default_date_to, IntervalType.day)

        self.assertEqual(10, response.results[0]["count"])

    def test_trends_query_data(self):
        self._create_test_events()

        response = self._run_trends_query(self.default_date_from, self.default_date_to, IntervalType.day)

        self.assertEqual([1, 0, 1, 3, 1, 0, 2, 0, 1, 0, 1], response.results[0]["data"])

    def test_trends_query_days(self):
        self._create_test_events()

        response = self._run_trends_query(self.default_date_from, self.default_date_to, IntervalType.day)

        self.assertEqual(
            [
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
            response.results[0]["days"],
        )

    def test_trends_query_labels(self):
        self._create_test_events()

        response = self._run_trends_query(self.default_date_from, self.default_date_to, IntervalType.day)

        self.assertEqual(
            [
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
            response.results[0]["labels"],
        )

    def test_trends_query_multiple_series(self):
        self._create_test_events()

        response = self._run_trends_query(
            self.default_date_from,
            self.default_date_to,
            IntervalType.day,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
        )

        self.assertEqual(2, len(response.results))

        self.assertEqual("$pageview", response.results[0]["label"])
        self.assertEqual("$pageleave", response.results[1]["label"])

        self.assertEqual(10, response.results[0]["count"])
        self.assertEqual(6, response.results[1]["count"])

        self.assertEqual([1, 0, 1, 3, 1, 0, 2, 0, 1, 0, 1], response.results[0]["data"])
        self.assertEqual([0, 0, 1, 1, 3, 0, 0, 1, 0, 0, 0], response.results[1]["data"])

    def test_trends_query_formula(self):
        self._create_test_events()

        response = self._run_trends_query(
            self.default_date_from,
            self.default_date_to,
            IntervalType.day,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(formula="A+B"),
        )

        self.assertEqual(1, len(response.results))
        self.assertEqual(16, response.results[0]["count"])
        self.assertEqual("Formula (A+B)", response.results[0]["label"])
        self.assertEqual([1, 0, 2, 4, 4, 0, 2, 1, 1, 0, 1], response.results[0]["data"])

    def test_trends_query_compare(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-15",
            "2020-01-19",
            IntervalType.day,
            [EventsNode(event="$pageview")],
            TrendsFilter(compare=True),
        )

        self.assertEqual(2, len(response.results))

        self.assertEqual(True, response.results[0]["compare"])
        self.assertEqual(True, response.results[1]["compare"])

        self.assertEqual("current", response.results[0]["compare_label"])
        self.assertEqual("previous", response.results[1]["compare_label"])

        self.assertEqual(
            [
                "2020-01-15",
                "2020-01-16",
                "2020-01-17",
                "2020-01-18",
                "2020-01-19",
            ],
            response.results[0]["days"],
        )
        self.assertEqual(
            [
                "2020-01-10",
                "2020-01-11",
                "2020-01-12",
                "2020-01-13",
                "2020-01-14",
            ],
            response.results[1]["days"],
        )

        self.assertEqual(["day 0", "day 1", "day 2", "day 3", "day 4"], response.results[0]["labels"])
        self.assertEqual(["day 0", "day 1", "day 2", "day 3", "day 4"], response.results[1]["labels"])

    def test_trends_query_formula_with_compare(self):
        self._create_test_events()

        response = self._run_trends_query(
            "2020-01-15",
            "2020-01-19",
            IntervalType.day,
            [EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
            TrendsFilter(formula="A+B", compare=True),
        )

        self.assertEqual(2, len(response.results))

        self.assertEqual(5, response.results[0]["count"])
        self.assertEqual(10, response.results[1]["count"])

        self.assertEqual(True, response.results[0]["compare"])
        self.assertEqual(True, response.results[1]["compare"])

        self.assertEqual("current", response.results[0]["compare_label"])
        self.assertEqual("previous", response.results[1]["compare_label"])

        self.assertEqual("Formula (A+B)", response.results[0]["label"])
        self.assertEqual("Formula (A+B)", response.results[1]["label"])
