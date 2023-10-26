import json
import random
import uuid
from typing import Any, Dict, Literal, Optional

from freezegun.api import freeze_time
from rest_framework import status

from posthog.models.filters.mixins.base import BreakdownType
from posthog.models.group.util import create_group
from posthog.queries.properties_timeline.properties_timeline import (
    PropertiesTimelineResult,
)
from posthog.settings.dynamic_settings import CONSTANCE_CONFIG
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)


def properties_timeline_test_factory(actor_type: Literal["person", "group"]):
    materialized_column_kwargs = (
        {"person_properties": ["foo", "bar"]} if actor_type == "person" else {"group_properties": ["foo", "bar"]}
    )
    main_actor_id = uuid.UUID("12345678-0000-0000-0000-000000000001") if actor_type == "person" else "test"

    class TestPropertiesTimeline(ClickhouseTestMixin, APIBaseTest):
        maxDiff = None

        def _create_actor(self, properties: dict) -> str:
            """Create actor of relevant type and return its UUID (for persons) or key (for groups)."""
            if actor_type == "person":
                person = _create_person(
                    team=self.team,
                    distinct_ids=["abcd"],
                    uuid=main_actor_id,
                    properties=properties,
                )
                return str(person.uuid)
            else:
                group = create_group(
                    team_id=self.team.pk,
                    group_type_index=0,
                    group_key=str(main_actor_id),
                    properties=properties,
                )
                return group.group_key

        def _create_event(self, event: str, timestamp: str, actor_properties: dict):
            create_event_kwargs: Dict[str, Any] = {}
            if actor_type == "person":
                create_event_kwargs["person_id"] = main_actor_id
                create_event_kwargs["person_properties"] = actor_properties
            else:
                create_event_kwargs["properties"] = {"$group_0": main_actor_id}
                create_event_kwargs["group_0_properties"] = actor_properties

            _create_event(
                team=self.team,
                event=event,
                timestamp=timestamp,
                distinct_id=str(random.randint(1, 1000)),
                **create_event_kwargs,
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
                f"/api/person/{main_actor_id}/properties_timeline"
                f"?events={json.dumps(events or [])}&actions={json.dumps(actions or [])}"
                f"&properties={json.dumps(properties or [])}&display={display}"
                f"&date_from={date_from or ''}&date_to={date_to or ''}&interval={interval or ''}"
                f"&breakdown={breakdown or ''}&breakdown_type={(breakdown_type or actor_type) if breakdown else ''}"
            )
            properties_timeline = self.client.get(url)
            self.assertEqual(properties_timeline.status_code, expected_status)
            return properties_timeline.json()

        @also_test_with_materialized_columns(**materialized_column_kwargs)
        @snapshot_clickhouse_queries
        def test_timeline_for_new_actor_with_one_event_in_range(self):
            self._create_actor({"foo": "abc", "bar": 123})
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

        @also_test_with_materialized_columns(**materialized_column_kwargs)
        @snapshot_clickhouse_queries
        def test_timeline_for_new_actor_with_one_event_before_range(self):
            self._create_actor({"foo": "abc", "bar": 123})
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

        @also_test_with_materialized_columns(**materialized_column_kwargs)
        @snapshot_clickhouse_queries
        def test_timeline_with_two_events_in_range_using_filter_on_series(self):
            self._create_actor({"foo": "abc", "bar": 123})
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

        @also_test_with_materialized_columns(**materialized_column_kwargs)
        @snapshot_clickhouse_queries
        def test_timeline_with_two_events_in_range_using_breakdown(self):
            self._create_actor({"foo": "abc", "bar": 123})
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
        @also_test_with_materialized_columns(**materialized_column_kwargs)
        def test_timeline_for_existing_actor_with_three_events_and_return_to_previous_value(self):
            self._create_actor({"foo": "abc", "bar": 123})
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
        @also_test_with_materialized_columns(person_properties=["bar"], materialize_only_with_person_on_events=True)
        def test_timeline_for_existing_person_with_three_events_and_return_to_previous_value_at_single_day_point(self):
            self._create_actor(properties={"foo": "abc", "bar": 123})
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
        @also_test_with_materialized_columns(person_properties=["bar"], materialize_only_with_person_on_events=True)
        def test_timeline_for_existing_person_with_three_events_and_return_to_previous_value_at_single_hour_point(self):
            self._create_actor(properties={"foo": "abc", "bar": 123})
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
        @also_test_with_materialized_columns(person_properties=["bar"], materialize_only_with_person_on_events=True)
        def test_timeline_for_existing_person_with_three_events_and_return_to_previous_value_at_single_month_point(
            self,
        ):
            self._create_actor(properties={"foo": "abc", "bar": 123})
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
        @also_test_with_materialized_columns(person_properties=["bar"], materialize_only_with_person_on_events=True)
        def test_timeline_for_existing_person_with_three_events_and_return_to_previous_value_using_relative_date_from(
            self,
        ):
            self._create_actor(properties={"foo": "abc", "bar": 123})
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
        @also_test_with_materialized_columns(**materialized_column_kwargs)
        def test_timeline_for_existing_actor_with_six_events_but_only_two_relevant_changes(self):
            self._create_actor({"foo": "abc", "bar": 123})
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
            self._create_actor({"foo": "abc", "bar": 123})
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
            self._create_actor({"foo": "abc", "bar": 123})
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

    return TestPropertiesTimeline


# Only test person properties timeline if persons-on-events is enabled
# Using CONSTANCE_CONFIG instead of get_instance_setting, becasue DB access is only allowed _inside_ the Test* class
if CONSTANCE_CONFIG["PERSON_ON_EVENTS_ENABLED"][0]:

    class TestPersonPropertiesTimeline(properties_timeline_test_factory(actor_type="person")):  # type: ignore
        pass


# TODO: Uncomment below when groups-on-events is released, and make sure everything works
# if CONSTANCE_CONFIG["GROUPS_ON_EVENTS_ENABLED"][0]:
#
#     class TestGroupPropertiesTimeline(properties_timeline_test_factory(actor_type="group")):  # type: ignore
#         pass
