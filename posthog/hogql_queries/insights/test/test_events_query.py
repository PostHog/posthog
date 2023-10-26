from typing import Tuple, Any

from freezegun import freeze_time

from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.schema import (
    EventsQuery,
    EventPropertyFilter,
    PropertyOperator,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
)


class TestEventsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_events(self, data: list[Tuple[str, str, Any]], event="$pageview"):
        person_result = []
        for distinct_id, timestamp, event_properties in data:
            with freeze_time(timestamp):
                person_result.append(
                    _create_person(
                        team_id=self.team.pk,
                        distinct_ids=[distinct_id],
                        properties={
                            "name": distinct_id,
                        },
                    )
                )
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=distinct_id,
                    timestamp=timestamp,
                    properties=event_properties,
                )
        return person_result

    def _create_boolean_field_test_events(self):
        self._create_events(
            data=[
                (
                    "p_true",
                    "2020-01-11T12:00:01Z",
                    {"boolean_field": True},
                ),
                (
                    "p_false",
                    "2020-01-11T12:00:02Z",
                    {"boolean_field": False},
                ),
                (
                    "p_notset",
                    "2020-01-11T12:00:04Z",
                    {},
                ),
                (
                    "p_null",
                    "2020-01-11T12:00:04Z",
                    {"boolean_field": None},
                ),
            ]
        )

    def _run_boolean_field_query(self, filter: EventPropertyFilter):
        with freeze_time("2020-01-11T12:01:00"):
            query = EventsQuery(
                after="-24h",
                event="$pageview",
                kind="EventsQuery",
                orderBy=["timestamp ASC"],
                select=["*"],
                properties=[filter],
            )

            runner = EventsQueryRunner(query=query, team=self.team)
            return runner.run().results

    def test_is_not_set_boolean(self):
        # see https://github.com/PostHog/posthog/issues/18030
        self._create_boolean_field_test_events()
        results = self._run_boolean_field_query(
            EventPropertyFilter(
                type="event",
                key="boolean_field",
                operator=PropertyOperator.is_not_set,
                value=PropertyOperator.is_not_set,
            )
        )

        self.assertEqual({"p_notset", "p_null"}, set(row[0]["distinct_id"] for row in results))

    def test_is_set_boolean(self):
        self._create_boolean_field_test_events()

        results = self._run_boolean_field_query(
            EventPropertyFilter(
                type="event",
                key="boolean_field",
                operator=PropertyOperator.is_set,
                value=PropertyOperator.is_set,
            )
        )

        self.assertEqual({"p_true", "p_false"}, set(row[0]["distinct_id"] for row in results))
