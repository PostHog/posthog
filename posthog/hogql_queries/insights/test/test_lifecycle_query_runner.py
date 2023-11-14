from datetime import datetime
from freezegun import freeze_time
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.lifecycle_query_runner import LifecycleQueryRunner
from posthog.models.utils import UUIDT
from posthog.schema import (
    DateRange,
    IntervalType,
    LifecycleQuery,
    EventsNode,
    EventPropertyFilter,
    PropertyOperator,
    PersonPropertyFilter,
    ActionsNode,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from posthog.models import Action, ActionStep
from posthog.models.instance_setting import get_instance_setting


def create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    event_name = kwargs.pop("event_name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=event_name)
    return action


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
                    "label": "$pageview - new",
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
                    "action": {
                        "id": "$pageview",
                        "math": "total",
                        "name": "$pageview",
                        "order": 0,
                        "type": "events",
                    },
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
                    "label": "$pageview - returning",
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
                    "action": {
                        "id": "$pageview",
                        "math": "total",
                        "name": "$pageview",
                        "order": 0,
                        "type": "events",
                    },
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
                    "label": "$pageview - resurrecting",
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
                    "action": {
                        "id": "$pageview",
                        "math": "total",
                        "name": "$pageview",
                        "order": 0,
                        "type": "events",
                    },
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
                    "label": "$pageview - dormant",
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
                    "action": {
                        "id": "$pageview",
                        "math": "total",
                        "name": "$pageview",
                        "order": 0,
                        "type": "events",
                    },
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

        result = (
            LifecycleQueryRunner(
                team=self.team,
                query=LifecycleQuery(
                    dateRange=DateRange(date_from="2020-01-12T00:00:00Z", date_to="2020-01-19T00:00:00Z"),
                    interval=IntervalType.day,
                    series=[EventsNode(event="$pageview")],
                ),
            )
            .calculate()
            .results
        )
        assert result[0]["label"] == "$pageview - new"

        assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, -2, -1, 0, -2, 0, -1, 0]},
                {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [1, 0, 0, 1, 0, 1, 0, 1]},
                {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
            ],
        )

    def test_lifecycle_trend_all_events(self):
        self._create_events(
            event="$pageview",
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
            ],
        )
        self._create_events(
            event="$other",
            data=[
                ("p3", ["2020-01-12T12:00:00Z"]),
                ("p4", ["2020-01-15T12:00:00Z"]),
            ],
        )

        result = (
            LifecycleQueryRunner(
                team=self.team,
                query=LifecycleQuery(
                    dateRange=DateRange(date_from="2020-01-12T00:00:00Z", date_to="2020-01-19T00:00:00Z"),
                    interval=IntervalType.day,
                    series=[EventsNode(event=None)],
                ),
            )
            .calculate()
            .results
        )

        assert result[0]["label"] == "All events - new"

        assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, -2, -1, 0, -2, 0, -1, 0]},
                {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [1, 0, 0, 1, 0, 1, 0, 1]},
                {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
            ],
        )

    def test_lifecycle_trend_with_zero_person_ids(self):
        # only a person-on-event test
        if not get_instance_setting("PERSON_ON_EVENTS_ENABLED"):
            return True

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

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p5",
            timestamp="2020-01-13T12:00:00Z",
            person_id="00000000-0000-0000-0000-000000000000",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p5",
            timestamp="2020-01-14T12:00:00Z",
            person_id="00000000-0000-0000-0000-000000000000",
        )

        result = (
            LifecycleQueryRunner(
                team=self.team,
                query=LifecycleQuery(
                    dateRange=DateRange(date_from="2020-01-12T00:00:00Z", date_to="2020-01-19T00:00:00Z"),
                    interval=IntervalType.day,
                    series=[EventsNode(event="$pageview")],
                ),
            )
            .calculate()
            .results
        )

        assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, -2, -1, 0, -2, 0, -1, 0]},
                {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [1, 0, 0, 1, 0, 1, 0, 1]},
                {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
            ],
        )

    def test_lifecycle_trend_prop_filtering(self):
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"$number": 1},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-12T12:00:00Z",
            properties={"$number": 1},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-13T12:00:00Z",
            properties={"$number": 1},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-15T12:00:00Z",
            properties={"$number": 1},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-17T12:00:00Z",
            properties={"$number": 1},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-19T12:00:00Z",
            properties={"$number": 1},
        )

        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-09T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-12T12:00:00Z",
        )

        _create_person(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "p3"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp="2020-01-12T12:00:00Z",
        )

        _create_person(team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "p4"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p4",
            timestamp="2020-01-15T12:00:00Z",
        )

        result = (
            LifecycleQueryRunner(
                team=self.team,
                query=LifecycleQuery(
                    dateRange=DateRange(date_from="2020-01-12T00:00:00Z", date_to="2020-01-19T00:00:00Z"),
                    interval=IntervalType.day,
                    series=[EventsNode(event="$pageview")],
                    properties=[EventPropertyFilter(key="$number", value="1", operator=PropertyOperator.exact)],
                ),
            )
            .calculate()
            .results
        )

        assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, 0, -1, 0, -1, 0, -1, 0]},
                {"status": "new", "data": [0, 0, 0, 0, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [0, 0, 0, 1, 0, 1, 0, 1]},
                {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
            ],
        )

        # entities filtering
        result = (
            LifecycleQueryRunner(
                team=self.team,
                query=LifecycleQuery(
                    dateRange=DateRange(date_from="2020-01-12T00:00:00Z", date_to="2020-01-19T00:00:00Z"),
                    interval=IntervalType.day,
                    series=[
                        EventsNode(
                            event="$pageview",
                            properties=[EventPropertyFilter(key="$number", value="1", operator=PropertyOperator.exact)],
                        )
                    ],
                ),
            )
            .calculate()
            .results
        )

        assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, 0, -1, 0, -1, 0, -1, 0]},
                {"status": "new", "data": [0, 0, 0, 0, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [0, 0, 0, 1, 0, 1, 0, 1]},
                {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
            ],
        )

    def test_lifecycle_trend_person_prop_filtering(self):
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"$number": 1},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-12T12:00:00Z",
            properties={"$number": 1},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-13T12:00:00Z",
            properties={"$number": 1},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-15T12:00:00Z",
            properties={"$number": 1},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-17T12:00:00Z",
            properties={"$number": 1},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-19T12:00:00Z",
            properties={"$number": 1},
        )

        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-09T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-12T12:00:00Z",
        )

        _create_person(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "p3"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp="2020-01-12T12:00:00Z",
        )

        _create_person(team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "p4"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p4",
            timestamp="2020-01-15T12:00:00Z",
        )

        result = (
            LifecycleQueryRunner(
                team=self.team,
                query=LifecycleQuery(
                    dateRange=DateRange(date_from="2020-01-12T00:00:00Z", date_to="2020-01-19T00:00:00Z"),
                    interval=IntervalType.day,
                    series=[
                        EventsNode(
                            event="$pageview",
                            properties=[PersonPropertyFilter(key="name", value="p1", operator=PropertyOperator.exact)],
                        )
                    ],
                ),
            )
            .calculate()
            .results
        )

        assertLifecycleResults(
            result,
            [
                {"status": "new", "data": [0, 0, 0, 0, 0, 0, 0, 0]},
                {"status": "returning", "data": [1, 1, 0, 0, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [0, 0, 0, 1, 0, 1, 0, 1]},
                {"status": "dormant", "data": [0, 0, -1, 0, -1, 0, -1, 0]},
            ],
        )

    def test_lifecycle_trends_distinct_id_repeat(self):
        with freeze_time("2020-01-12T12:00:00Z"):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=["p1", "another_p1"],
                properties={"name": "p1"},
            )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-12T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="another_p1",
            timestamp="2020-01-14T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-15T12:00:00Z",
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-17T12:00:00Z",
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-19T12:00:00Z",
        )

        result = (
            LifecycleQueryRunner(
                team=self.team,
                query=LifecycleQuery(
                    dateRange=DateRange(date_from="2020-01-12T00:00:00Z", date_to="2020-01-19T00:00:00Z"),
                    interval=IntervalType.day,
                    series=[EventsNode(event="$pageview")],
                ),
            )
            .calculate()
            .results
        )

        assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, -1, 0, 0, -1, 0, -1, 0]},
                {"status": "new", "data": [1, 0, 0, 0, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [0, 0, 1, 0, 0, 1, 0, 1]},
                {"status": "returning", "data": [0, 0, 0, 1, 0, 0, 0, 0]},
            ],
        )

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

        pageview_action = create_action(team=self.team, name="$pageview", event_name="$pageview")

        result = (
            LifecycleQueryRunner(
                team=self.team,
                query=LifecycleQuery(
                    dateRange=DateRange(date_from="2020-01-12T00:00:00Z", date_to="2020-01-19T00:00:00Z"),
                    interval=IntervalType.day,
                    series=[ActionsNode(id=pageview_action.pk)],
                ),
            )
            .calculate()
            .results
        )

        assertLifecycleResults(
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
            result = (
                LifecycleQueryRunner(
                    team=self.team,
                    query=LifecycleQuery(
                        dateRange=DateRange(date_from="all"),
                        interval=IntervalType.day,
                        series=[EventsNode(event="$pageview")],
                    ),
                )
                .calculate()
                .results
            )

        assertLifecycleResults(
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

        result = (
            LifecycleQueryRunner(
                team=self.team,
                query=LifecycleQuery(
                    dateRange=DateRange(date_from="2020-02-05T00:00:00Z", date_to="2020-03-09T00:00:00Z"),
                    interval=IntervalType.week,
                    series=[EventsNode(event="$pageview")],
                ),
            )
            .calculate()
            .results
        )

        self.assertEqual(
            result[0]["days"],
            [
                "2020-02-03",
                "2020-02-10",
                "2020-02-17",
                "2020-02-24",
                "2020-03-02",
                "2020-03-09",
            ],
        )

        assertLifecycleResults(
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
                ("p2", ["2019-12-09T12:00:00Z", "2020-02-12T12:00:00Z"]),
                ("p3", ["2020-02-12T12:00:00Z"]),
                ("p4", ["2020-05-15T12:00:00Z"]),
            ]
        )

        result = (
            LifecycleQueryRunner(
                team=self.team,
                query=LifecycleQuery(
                    dateRange=DateRange(date_from="2020-02-01T00:00:00Z", date_to="2020-09-01T00:00:00Z"),
                    interval=IntervalType.month,
                    series=[EventsNode(event="$pageview")],
                ),
            )
            .calculate()
            .results
        )

        assertLifecycleResults(
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

        result = (
            LifecycleQueryRunner(
                team=self.team,
                query=LifecycleQuery(
                    dateRange=DateRange(date_from="2020-01-12T00:00:00Z", date_to="2020-01-19T00:00:00Z"),
                    interval=IntervalType.day,
                    series=[EventsNode(event="$pageview")],
                    filterTestAccounts=True,
                ),
            )
            .calculate()
            .results
        )

        assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, -2, 0, 0, -1, 0, 0, 0]},
                {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [1, 0, 0, 0, 0, 0, 0, 0]},
                {"status": "returning", "data": [0, 0, 0, 0, 0, 0, 0, 0]},
            ],
        )

    @snapshot_clickhouse_queries
    def test_timezones(self):
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

        result = (
            LifecycleQueryRunner(
                team=self.team,
                query=LifecycleQuery(
                    dateRange=DateRange(date_from="2020-01-12T00:00:00Z", date_to="2020-01-19T00:00:00Z"),
                    interval=IntervalType.day,
                    series=[EventsNode(event="$pageview")],
                ),
            )
            .calculate()
            .results
        )

        assertLifecycleResults(
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

        result_pacific = (
            LifecycleQueryRunner(
                team=self.team,
                query=LifecycleQuery(
                    dateRange=DateRange(date_from="2020-01-12T00:00:00Z", date_to="2020-01-19T00:00:00Z"),
                    interval=IntervalType.day,
                    series=[EventsNode(event="$pageview")],
                ),
            )
            .calculate()
            .results
        )

        assertLifecycleResults(
            result_pacific,
            [
                {
                    "status": "dormant",
                    "data": [-1.0, -2.0, -1.0, 0.0, -2.0, 0.0, -1.0, 0.0],
                },
                {"status": "new", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [1, 1, 0, 1, 0, 1, 0, 1]},
                {"status": "returning", "data": [0, 0, 0, 0, 0, 0, 0, 0]},
            ],
        )

    # Ensure running the query with sampling works + generate a snapshot that shows sampling in the query
    @snapshot_clickhouse_queries
    def test_sampling(self):
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

        LifecycleQueryRunner(
            team=self.team,
            query=LifecycleQuery(
                dateRange=DateRange(date_from="2020-01-12T00:00:00Z", date_to="2020-01-19T00:00:00Z"),
                interval=IntervalType.day,
                series=[EventsNode(event="$pageview")],
                samplingFactor=0.1,
            ),
        ).calculate()


def assertLifecycleResults(results, expected):
    sorted_results = [{"status": r["status"], "data": r["data"]} for r in sorted(results, key=lambda r: r["status"])]
    sorted_expected = list(sorted(expected, key=lambda r: r["status"]))

    assert sorted_results == sorted_expected
