import json
import uuid
import random
from typing import Optional

from freezegun.api import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from rest_framework import status

from posthog.models.filters.mixins.base import BreakdownType
from posthog.queries.properties_timeline.properties_timeline import PropertiesTimelineResult

MATERIALIZED_COLUMN_KWARGS = {"person_properties": ["foo", "bar"]}
TEST_PERSON_ID = uuid.UUID("12345678-0000-0000-0000-000000000001")


class TestPersonPropertiesTimeline(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_person(self, properties: dict) -> str:
        """Create person and return its UUID."""
        person = _create_person(
            team=self.team,
            distinct_ids=["abcd"],
            uuid=TEST_PERSON_ID,
            properties=properties,
        )
        return str(person.uuid)

    def _create_event(self, event: str, timestamp: str, actor_properties: dict):
        _create_event(
            team=self.team,
            event=event,
            timestamp=timestamp,
            distinct_id=str(random.randint(1, 1000)),
            person_id=TEST_PERSON_ID,
            person_properties=actor_properties,
        )

    def _get_timeline_result(
        self,
        *,
        events: Optional[list] = None,
        actions: Optional[list] = None,
        properties: Optional[list] = None,
        breakdown: Optional[str] = None,
        breakdown_type: Optional[BreakdownType] = None,
        date_from: Optional[str],
        date_to: Optional[str],
        display: str = "ActionsTable",
        interval: Optional[str] = None,
        expected_status: int = status.HTTP_200_OK,
    ) -> PropertiesTimelineResult:
        url = (
            f"/api/person/{TEST_PERSON_ID}/properties_timeline"
            f"?events={json.dumps(events or [])}&actions={json.dumps(actions or [])}"
            f"&properties={json.dumps(properties or [])}&display={display}"
            f"&date_from={date_from or ''}&date_to={date_to or ''}&interval={interval or ''}"
            f"&breakdown={breakdown or ''}&breakdown_type={(breakdown_type or 'person') if breakdown else ''}"
        )
        properties_timeline = self.client.get(url)
        self.assertEqual(properties_timeline.status_code, expected_status)
        return properties_timeline.json()

    @also_test_with_materialized_columns(**MATERIALIZED_COLUMN_KWARGS)
    @snapshot_clickhouse_queries
    def test_timeline_for_new_actor_with_one_event_in_range(self):
        self._create_person({"foo": "abc", "bar": 123})
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 123},
            timestamp="2020-01-01T00:00:00Z",  # Exactly the same as date_from
        )
        flush_persons_and_events()

        timeline = self._get_timeline_result(
            events=[
                {
                    "id": "$pageview",
                }
            ],
            properties=[{"key": "bar", "value": "xyz", "type": "person"}],
            date_from="2020-01-01",
            date_to="2020-01-05",
        )

        self.assertEqual(
            timeline,
            {
                "points": [
                    {
                        "properties": {"foo": "abc", "bar": 123},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-01T00:00:00Z",
                    }
                ],
                "crucial_property_keys": ["bar"],
                "effective_date_from": "2020-01-01T00:00:00+00:00",
                "effective_date_to": "2020-01-05T23:59:59.999999+00:00",
            },
        )

    @also_test_with_materialized_columns(**MATERIALIZED_COLUMN_KWARGS)
    @snapshot_clickhouse_queries
    def test_timeline_for_new_actor_with_one_event_before_range(self):
        self._create_person({"foo": "abc", "bar": 123})
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 123},
            timestamp="2019-12-27T00:00:00Z",  # Before date_from
        )
        flush_persons_and_events()

        timeline = self._get_timeline_result(
            events=[
                {
                    "id": "$pageview",
                }
            ],
            properties=[{"key": "bar", "value": "xyz", "type": "person"}],
            date_from="2020-01-01",
            date_to="2020-01-05",
        )

        self.assertEqual(
            timeline,
            {
                "points": [],  # No relevant events in range
                "crucial_property_keys": ["bar"],
                "effective_date_from": "2020-01-01T00:00:00+00:00",
                "effective_date_to": "2020-01-05T23:59:59.999999+00:00",
            },
        )

    @also_test_with_materialized_columns(**MATERIALIZED_COLUMN_KWARGS)
    @snapshot_clickhouse_queries
    def test_timeline_with_two_events_in_range_using_filter_on_series(self):
        self._create_person({"foo": "abc", "bar": 123})
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 123},
            timestamp="2020-01-01T00:00:00Z",  # Exactly the same as date_from
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "klm", "bar": 123},
            timestamp="2020-01-01T21:37:00Z",
        )
        flush_persons_and_events()

        timeline = self._get_timeline_result(
            events=[
                {
                    "id": "$pageview",
                    "properties": [
                        {
                            "key": "foo",
                            "type": "person",
                            "value": ["whatever"],
                            "operator": "exact",
                        },
                        {
                            "key": "fin",
                            "type": "event",
                            "value": ["anything"],
                            "operator": "exact",
                        },
                    ],
                }
            ],
            properties=[{"key": "bar", "value": "xyz", "type": "person"}],
            date_from="2020-01-01",
            date_to="2020-01-05",
        )

        self.assertEqual(
            timeline,
            {
                "points": [
                    {
                        "properties": {"foo": "abc", "bar": 123},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-01T00:00:00Z",
                    },
                    {
                        "properties": {"foo": "klm", "bar": 123},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-01T21:37:00Z",
                    },
                ],
                "crucial_property_keys": ["bar", "foo"],
                "effective_date_from": "2020-01-01T00:00:00+00:00",
                "effective_date_to": "2020-01-05T23:59:59.999999+00:00",
            },
        )

    @also_test_with_materialized_columns(**MATERIALIZED_COLUMN_KWARGS)
    @snapshot_clickhouse_queries
    def test_timeline_with_two_events_in_range_using_breakdown(self):
        self._create_person({"foo": "abc", "bar": 123})
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 123},
            timestamp="2020-01-01T00:00:00Z",  # Exactly the same as date_from
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "klm", "bar": 123},
            timestamp="2020-01-01T21:37:00Z",
        )
        flush_persons_and_events()

        timeline = self._get_timeline_result(
            events=[
                {
                    "id": "$pageview",
                }
            ],
            breakdown="foo",
            properties=[{"key": "bar", "value": "xyz", "type": "person"}],
            date_from="2020-01-01",
            date_to="2020-01-05",
        )

        self.assertEqual(
            timeline,
            {
                "points": [
                    {
                        "properties": {"foo": "abc", "bar": 123},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-01T00:00:00Z",
                    },
                    {
                        "properties": {"foo": "klm", "bar": 123},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-01T21:37:00Z",
                    },
                ],
                "crucial_property_keys": ["bar", "foo"],
                "effective_date_from": "2020-01-01T00:00:00+00:00",
                "effective_date_to": "2020-01-05T23:59:59.999999+00:00",
            },
        )

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(**MATERIALIZED_COLUMN_KWARGS)
    def test_timeline_for_existing_actor_with_three_events_and_return_to_previous_value(self):
        self._create_person({"foo": "abc", "bar": 123})
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 456},  # Initial bar
            timestamp="2020-01-02T00:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 123},  # Changed bar
            timestamp="2020-01-03T00:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={
                "foo": "abc",
                "bar": 456,
            },  # Changed bar back to initial value
            timestamp="2020-01-04T00:00:00Z",
        )
        flush_persons_and_events()

        timeline = self._get_timeline_result(
            events=[
                {
                    "id": "$pageview",
                }
            ],
            properties=[{"key": "bar", "value": "xyz", "type": "person"}],
            date_from="2020-01-01",
            date_to="2020-01-05",
        )

        self.assertEqual(
            timeline,
            {
                "points": [
                    {
                        "properties": {"foo": "abc", "bar": 456},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-02T00:00:00Z",
                    },
                    {
                        "properties": {"foo": "abc", "bar": 123},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-03T00:00:00Z",
                    },
                    {
                        "properties": {"foo": "abc", "bar": 456},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-04T00:00:00Z",
                    },
                ],
                "crucial_property_keys": ["bar"],
                "effective_date_from": "2020-01-01T00:00:00+00:00",
                "effective_date_to": "2020-01-05T23:59:59.999999+00:00",
            },
        )

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(
        person_properties=["bar"],
    )
    def test_timeline_for_existing_person_with_three_events_and_return_to_previous_value_at_single_day_point(self):
        self._create_person(properties={"foo": "abc", "bar": 123})
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 456},  # Initial bar
            timestamp="2020-01-02T00:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 123},  # Changed bar
            timestamp="2020-01-02T07:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={
                "foo": "abc",
                "bar": 456,
            },  # Changed bar back to initial value
            timestamp="2020-01-02T14:00:00Z",
        )
        flush_persons_and_events()

        timeline = self._get_timeline_result(
            events=[
                {
                    "id": "$pageview",
                }
            ],
            properties=[{"key": "bar", "value": "xyz", "type": "person"}],
            display="ActionsLineGraph",
            date_from="2020-01-02T00:00:00Z",
            date_to="2020-01-02T00:00:00Z",
            # For some legacy reason data point-specific date_from and date_to are the same in the persons modal
            # The backend needs interval to offset date_from properly
            interval="day",
        )

        self.assertEqual(
            timeline,
            {
                "points": [
                    {
                        "properties": {"foo": "abc", "bar": 456},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-02T00:00:00Z",
                    },
                    {
                        "properties": {"foo": "abc", "bar": 123},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-02T07:00:00Z",
                    },
                    {
                        "properties": {"foo": "abc", "bar": 456},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-02T14:00:00Z",
                    },
                ],
                "crucial_property_keys": ["bar"],
                "effective_date_from": "2020-01-02T00:00:00+00:00",
                "effective_date_to": "2020-01-02T23:59:59.999999+00:00",
            },
        )

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(
        person_properties=["bar"],
    )
    def test_timeline_for_existing_person_with_three_events_and_return_to_previous_value_at_single_hour_point(self):
        self._create_person(properties={"foo": "abc", "bar": 123})
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 456},  # Initial bar
            timestamp="2020-01-02T00:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 123},  # Changed bar
            timestamp="2020-01-02T00:20:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={
                "foo": "abc",
                "bar": 456,
            },  # Changed bar back to initial value
            timestamp="2020-01-02T00:40:00Z",
        )
        flush_persons_and_events()

        timeline = self._get_timeline_result(
            events=[
                {
                    "id": "$pageview",
                }
            ],
            properties=[{"key": "bar", "value": "xyz", "type": "person"}],
            display="ActionsLineGraph",
            date_from="2020-01-02T00:00:00Z",
            date_to="2020-01-02T00:00:00Z",
            interval="hour",
        )

        self.assertEqual(
            timeline,
            {
                "points": [
                    {
                        "properties": {"foo": "abc", "bar": 456},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-02T00:00:00Z",
                    },
                    {
                        "properties": {"foo": "abc", "bar": 123},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-02T00:20:00Z",
                    },
                    {
                        "properties": {"foo": "abc", "bar": 456},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-02T00:40:00Z",
                    },
                ],
                "crucial_property_keys": ["bar"],
                "effective_date_from": "2020-01-02T00:00:00+00:00",
                "effective_date_to": "2020-01-02T01:00:00+00:00",
            },
        )

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(
        person_properties=["bar"],
    )
    def test_timeline_for_existing_person_with_three_events_and_return_to_previous_value_at_single_month_point(
        self,
    ):
        self._create_person(properties={"foo": "abc", "bar": 123})
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 456},  # Initial bar
            timestamp="2020-01-01T00:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 123},  # Changed bar
            timestamp="2020-01-02T00:20:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={
                "foo": "abc",
                "bar": 456,
            },  # Changed bar back to initial value
            timestamp="2020-01-31T00:40:00Z",
        )
        flush_persons_and_events()

        timeline = self._get_timeline_result(
            events=[
                {
                    "id": "$pageview",
                }
            ],
            properties=[{"key": "bar", "value": "xyz", "type": "person"}],
            display="ActionsLineGraph",
            date_from="2020-01-01",
            date_to="2020-01-01",
            interval="month",
        )

        self.assertEqual(
            timeline,
            {
                "points": [
                    {
                        "properties": {"foo": "abc", "bar": 456},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-01T00:00:00Z",
                    },
                    {
                        "properties": {"foo": "abc", "bar": 123},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-02T00:20:00Z",
                    },
                    {
                        "properties": {"foo": "abc", "bar": 456},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-31T00:40:00Z",
                    },
                ],
                "crucial_property_keys": ["bar"],
                "effective_date_from": "2020-01-01T00:00:00+00:00",
                "effective_date_to": "2020-01-31T23:59:59.999999+00:00",
            },
        )

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(
        person_properties=["bar"],
    )
    def test_timeline_for_existing_person_with_three_events_and_return_to_previous_value_using_relative_date_from(
        self,
    ):
        self._create_person(properties={"foo": "abc", "bar": 123})
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 456},  # Initial bar
            timestamp="2020-01-02T00:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 123},  # Changed bar
            timestamp="2020-01-02T00:20:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={
                "foo": "abc",
                "bar": 456,
            },  # Changed bar back to initial value
            timestamp="2020-01-06T00:40:00Z",
        )
        flush_persons_and_events()

        with freeze_time("2020-01-09T21:37:00Z"):
            timeline = self._get_timeline_result(
                events=[
                    {
                        "id": "$pageview",
                    }
                ],
                properties=[{"key": "bar", "value": "xyz", "type": "person"}],
                date_from="-7d",
                date_to=None,
            )

        self.assertEqual(
            timeline,
            {
                "points": [
                    {
                        "properties": {"foo": "abc", "bar": 456},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-02T00:00:00Z",
                    },
                    {
                        "properties": {"foo": "abc", "bar": 123},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-02T00:20:00Z",
                    },
                    {
                        "properties": {"foo": "abc", "bar": 456},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-06T00:40:00Z",
                    },
                ],
                "crucial_property_keys": ["bar"],
                "effective_date_from": "2020-01-02T00:00:00+00:00",
                "effective_date_to": "2020-01-09T23:59:59.999999+00:00",
            },
        )

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(**MATERIALIZED_COLUMN_KWARGS)
    def test_timeline_for_existing_actor_with_six_events_but_only_two_relevant_changes(self):
        self._create_person({"foo": "abc", "bar": 123})
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 456},
            timestamp="2020-01-01T00:00:00Z",  # Exactly the same as date_from
        )
        self._create_event(
            event="whatever",  # This event is not a $pageview, so it must be ignored here
            actor_properties={"foo": "abc", "bar": 123},  # Changed bar
            timestamp="2020-01-02T00:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 123},  # Changed bar
            timestamp="2020-01-02T01:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 123},
            timestamp="2020-01-03T01:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 123},
            timestamp="2020-01-04T19:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 789},  # Changed bar
            timestamp="2020-01-04T19:00:01Z",
        )
        flush_persons_and_events()

        timeline = self._get_timeline_result(
            events=[
                {
                    "id": "$pageview",
                }
            ],
            properties=[{"key": "bar", "value": "xyz", "type": "person"}],
            date_from="2020-01-01",
            date_to="2020-01-05",
        )

        self.assertEqual(
            timeline,
            {
                "points": [
                    {
                        "properties": {"foo": "abc", "bar": 456},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-01T00:00:00Z",
                    },
                    {
                        "properties": {"foo": "abc", "bar": 123},
                        "relevant_event_count": 3,
                        "timestamp": "2020-01-02T01:00:00Z",
                    },
                    {
                        "properties": {"foo": "abc", "bar": 789},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-04T19:00:01Z",
                    },
                ],
                "crucial_property_keys": ["bar"],
                "effective_date_from": "2020-01-01T00:00:00+00:00",
                "effective_date_to": "2020-01-05T23:59:59.999999+00:00",
            },
        )

    @snapshot_clickhouse_queries
    def test_timeline_for_existing_actor_with_six_events_but_only_two_relevant_changes_without_filters(self):
        self._create_person({"foo": "abc", "bar": 123})
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 456},
            timestamp="2020-01-01T00:00:00Z",  # Exactly the same as date_from
        )
        self._create_event(
            event="whatever",  # This event is not a $pageview, but this doesn't matter here anyway
            actor_properties={"foo": "abc", "bar": 123},  # Changed bar
            timestamp="2020-01-01T01:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 123},  # Changed bar
            timestamp="2020-01-02T01:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 123},
            timestamp="2020-01-03T01:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 123},
            timestamp="2020-01-04T19:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 789},  # Changed bar
            timestamp="2020-01-04T19:00:01Z",
        )
        flush_persons_and_events()

        timeline = self._get_timeline_result(
            events=[
                {
                    "id": "$pageview",
                }
            ],
            date_from="2020-01-01",
            date_to="2020-01-05",
        )

        self.assertEqual(
            timeline,  # Without filters, NO changes are relevant
            {
                "points": [
                    {
                        "properties": {"foo": "abc", "bar": 456},
                        "relevant_event_count": 5,
                        "timestamp": "2020-01-01T00:00:00Z",
                    },
                ],
                "crucial_property_keys": [],
                "effective_date_from": "2020-01-01T00:00:00+00:00",
                "effective_date_to": "2020-01-05T23:59:59.999999+00:00",
            },
        )

    @snapshot_clickhouse_queries
    def test_timeline_for_existing_actor_with_six_events_but_only_two_relevant_changes_without_events(self):
        self._create_person({"foo": "abc", "bar": 123})
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 456},
            timestamp="2020-01-01T00:00:00Z",  # Exactly the same as date_from
        )
        self._create_event(
            event="whatever",  # This event is not a $pageview, but with no events/actions specified, it will be counted
            actor_properties={"foo": "abc", "bar": 123},  # Changed bar
            timestamp="2020-01-01T01:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 123},  # Changed bar
            timestamp="2020-01-02T01:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 123},
            timestamp="2020-01-03T01:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 123},
            timestamp="2020-01-04T19:00:00Z",
        )
        self._create_event(
            event="$pageview",
            actor_properties={"foo": "abc", "bar": 789},  # Changed bar
            timestamp="2020-01-04T19:00:01Z",
        )
        flush_persons_and_events()

        timeline = self._get_timeline_result(
            properties=[{"key": "bar", "value": "xyz", "type": "person"}],
            date_from="2020-01-01",
            date_to="2020-01-05",
        )

        self.assertEqual(
            timeline,
            {
                "points": [
                    {
                        "properties": {"foo": "abc", "bar": 456},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-01T00:00:00Z",
                    },
                    {
                        "properties": {"foo": "abc", "bar": 123},
                        "relevant_event_count": 4,
                        "timestamp": "2020-01-01T01:00:00Z",  # whatever event
                    },
                    {
                        "properties": {"foo": "abc", "bar": 789},
                        "relevant_event_count": 1,
                        "timestamp": "2020-01-04T19:00:01Z",
                    },
                ],
                "crucial_property_keys": ["bar"],
                "effective_date_from": "2020-01-01T00:00:00+00:00",
                "effective_date_to": "2020-01-05T23:59:59.999999+00:00",
            },
        )
