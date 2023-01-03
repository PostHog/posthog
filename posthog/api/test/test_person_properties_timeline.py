import datetime as dt
import json
from typing import Optional

from rest_framework import status

from posthog.queries.properties_timeline.properties_timeline import PropertiesTimelineResult
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
    test_with_materialized_columns,
)


class TestPersonPropertiesTimeline(ClickhouseTestMixin, APIBaseTest):
    @test_with_materialized_columns(person_properties=["bar"], materialize_only_with_person_on_events=True)
    @snapshot_clickhouse_queries
    def test_timeline_for_new_person_with_one_event_in_range(self):
        person = _create_person(team=self.team, distinct_ids=["1", "2", "3"], properties={"foo": "abc", "bar": 123})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 123},
            timestamp="2020-01-01T00:00:00Z",  # Exactly the same as date_from
        )
        flush_persons_and_events()

        timeline = self._get_person_properties_timeline(
            str(person.uuid),
            events=[
                {
                    "id": "$pageview",
                }
            ],
            properties=[{"key": "bar", "value": "xyz", "type": "person"}],
            date_from=dt.datetime(2020, 1, 1),
            date_to=dt.datetime(2020, 1, 5),
        )

        self.assertEqual(
            timeline,
            {
                "points": [
                    {
                        "properties": {"foo": "abc", "bar": 123},
                        "relevant_event_count": 1,  # 0 here means the person was created within range
                        "timestamp": "2020-01-01T00:00:00Z",
                    }
                ],
                "crucial_property_keys": ["bar"],
            },
        )

    @test_with_materialized_columns(person_properties=["bar"], materialize_only_with_person_on_events=True)
    @snapshot_clickhouse_queries
    def test_timeline_for_new_person_with_one_event_before_range(self):
        person = _create_person(team=self.team, distinct_ids=["1", "2", "3"], properties={"foo": "abc", "bar": 123})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 123},
            timestamp="2019-12-27T00:00:00Z",  # Before date_from
        )
        flush_persons_and_events()

        timeline = self._get_person_properties_timeline(
            str(person.uuid),
            events=[
                {
                    "id": "$pageview",
                }
            ],
            properties=[{"key": "bar", "value": "xyz", "type": "person"}],
            date_from=dt.datetime(2020, 1, 1),
            date_to=dt.datetime(2020, 1, 5),
        )

        self.assertEqual(
            timeline,
            {
                "points": [],  # No relevant events in range
                "crucial_property_keys": ["bar"],
            },
        )

    @snapshot_clickhouse_queries
    @test_with_materialized_columns(person_properties=["bar"], materialize_only_with_person_on_events=True)
    def test_timeline_for_existing_person_with_three_events_and_return_to_previous_value(self):
        person = _create_person(team=self.team, distinct_ids=["1", "2", "3"], properties={"foo": "abc", "bar": 123})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 456},  # Initial bar
            timestamp="2020-01-02T00:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="2",
            person_properties={"foo": "abc", "bar": 123},  # Changed bar
            timestamp="2020-01-03T00:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="3",
            person_properties={"foo": "abc", "bar": 456},  # Changed bar back to initial value
            timestamp="2020-01-04T00:00:00Z",
        )
        flush_persons_and_events()

        timeline = self._get_person_properties_timeline(
            str(person.uuid),
            events=[
                {
                    "id": "$pageview",
                }
            ],
            properties=[{"key": "bar", "value": "xyz", "type": "person"}],
            date_from=dt.datetime(2020, 1, 1),
            date_to=dt.datetime(2020, 1, 5),
        )

        self.assertEqual(
            timeline,
            {
                "points": [
                    {
                        "properties": {"foo": "abc", "bar": 456},
                        "relevant_event_count": 1,  # 0 here means the person was created within range
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
            },
        )

    @snapshot_clickhouse_queries
    @test_with_materialized_columns(person_properties=["bar"], materialize_only_with_person_on_events=True)
    def test_timeline_for_existing_person_with_six_events_but_only_two_relevant_changes(self):
        person = _create_person(team=self.team, distinct_ids=["1", "2", "3"], properties={"foo": "abc", "bar": 123})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 456},
            timestamp="2020-01-01T00:00:00Z",  # Exactly the same as date_from
        )
        _create_event(
            team=self.team,
            event="whatever",  # This event is not a $pageview, so it must be ignored here
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 123},  # Changed bar
            timestamp="2020-01-02T00:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 123},  # Changed bar
            timestamp="2020-01-02T01:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 123},
            timestamp="2020-01-03T01:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 123},
            timestamp="2020-01-04T19:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 789},  # Changed bar
            timestamp="2020-01-04T19:00:01Z",
        )
        flush_persons_and_events()

        timeline = self._get_person_properties_timeline(
            str(person.uuid),
            events=[
                {
                    "id": "$pageview",
                }
            ],
            properties=[{"key": "bar", "value": "xyz", "type": "person"}],
            date_from=dt.datetime(2020, 1, 1),
            date_to=dt.datetime(2020, 1, 5),
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
            },
        )

    @snapshot_clickhouse_queries
    def test_timeline_for_existing_person_with_six_events_but_only_two_relevant_changes_without_filters(self):
        person = _create_person(team=self.team, distinct_ids=["1", "2", "3"], properties={"foo": "abc", "bar": 123})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 456},
            timestamp="2020-01-01T00:00:00Z",  # Exactly the same as date_from
        )
        _create_event(
            team=self.team,
            event="whatever",  # This event is not a $pageview, but this doesn't matter here anyway
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 123},  # Changed bar
            timestamp="2020-01-01T01:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="2",
            person_properties={"foo": "abc", "bar": 123},  # Changed bar
            timestamp="2020-01-02T01:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 123},
            timestamp="2020-01-03T01:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 123},
            timestamp="2020-01-04T19:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 789},  # Changed bar
            timestamp="2020-01-04T19:00:01Z",
        )
        flush_persons_and_events()

        timeline = self._get_person_properties_timeline(
            str(person.uuid),
            events=[
                {
                    "id": "$pageview",
                }
            ],
            date_from=dt.datetime(2020, 1, 1),
            date_to=dt.datetime(2020, 1, 5),
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
            },
        )

    @snapshot_clickhouse_queries
    def test_timeline_for_existing_person_with_six_events_but_only_two_relevant_changes_without_events(self):
        person = _create_person(team=self.team, distinct_ids=["1", "2", "3"], properties={"foo": "abc", "bar": 123})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 456},
            timestamp="2020-01-01T00:00:00Z",  # Exactly the same as date_from
        )
        _create_event(
            team=self.team,
            event="whatever",  # This event is not a $pageview, but with no events/actions specified, it will be counted
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 123},  # Changed bar
            timestamp="2020-01-01T01:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 123},  # Changed bar
            timestamp="2020-01-02T01:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 123},
            timestamp="2020-01-03T01:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 123},
            timestamp="2020-01-04T19:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="1",
            person_properties={"foo": "abc", "bar": 789},  # Changed bar
            timestamp="2020-01-04T19:00:01Z",
        )
        flush_persons_and_events()

        timeline = self._get_person_properties_timeline(
            str(person.uuid),
            properties=[{"key": "bar", "value": "xyz", "type": "person"}],
            date_from=dt.datetime(2020, 1, 1),
            date_to=dt.datetime(2020, 1, 5),
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
            },
        )

    def _get_person_properties_timeline(
        self,
        person_id: str,
        *,
        events: Optional[list] = None,
        actions: Optional[list] = None,
        properties: Optional[list] = None,
        date_from: Optional[dt.datetime] = None,
        date_to: Optional[dt.datetime] = None,
        expected_status: int = status.HTTP_200_OK,
    ) -> PropertiesTimelineResult:
        url = (
            f"/api/person/{person_id}/properties_timeline"
            f"?events={json.dumps(events or [])}&actions={json.dumps(actions or [])}"
            f"&properties={json.dumps(properties or [])}"
            f"&date_from={date_from.isoformat() if date_from else ''}&date_to={date_to.isoformat() if date_to else ''}"
        )
        properties_timeline = self.client.get(url)
        self.assertEqual(properties_timeline.status_code, expected_status)
        return properties_timeline.json()
