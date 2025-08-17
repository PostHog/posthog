from datetime import timedelta
from uuid import uuid4

from dateutil.relativedelta import relativedelta
from freezegun import freeze_time

from posthog.models import Person
from posthog.models.utils import uuid7
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery
from posthog.session_recordings.queries.test.listing_recordings.test_base_session_recordings_list import (
    BaseTestSessionRecordingsList,
)
from posthog.session_recordings.queries.test.listing_recordings.test_utils import create_event
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.base import also_test_with_materialized_columns, snapshot_clickhouse_queries


@freeze_time("2021-01-01T13:46:23")
class TestSessionRecordingListEventFilters(BaseTestSessionRecordingsList):
    def test_event_filter(self):
        user = "test_event_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        session_id_one = f"test_event_filter-{str(uuid4())}"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago,
            properties={"$session_id": session_id_one, "$window_id": str(uuid4())},
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )

        self.assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ]
            },
            [session_id_one],
        )

        self.assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$autocapture",
                        "type": "events",
                        "order": 0,
                        "name": "$autocapture",
                    }
                ]
            },
            [],
        )

    @snapshot_clickhouse_queries
    def test_event_filter_has_ttl_applied_too(self):
        user = "test_event_filter_has_ttl_applied_too-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        session_id_one = f"test_event_filter_has_ttl_applied_too-{str(uuid4())}"

        # this is artificially incorrect data, the session events are within TTL
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        # but the page view event is outside TTL
        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago
            - relativedelta(days=SessionRecordingListFromQuery.SESSION_RECORDINGS_DEFAULT_LIMIT + 1),
            properties={"$session_id": session_id_one, "$window_id": str(uuid4())},
        )

        self.assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ]
            },
            [],
        )

        # without an event filter the recording is present, showing that the TTL was applied to the events table too
        # we want this to limit the amount of event data we query
        self.assert_query_matches_session_ids({}, [session_id_one])

    @snapshot_clickhouse_queries
    def test_event_filter_with_active_sessions(
        self,
    ):
        user = "test_basic_query-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id_total_is_61 = f"test_basic_query_active_sessions-total-{str(uuid4())}"
        session_id_active_is_61 = f"test_basic_query_active_sessions-active-{str(uuid4())}"

        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": session_id_total_is_61,
                "$window_id": str(uuid4()),
            },
        )
        produce_replay_summary(
            session_id=session_id_total_is_61,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp=self.an_hour_ago.isoformat().replace("T", " "),
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=61)).isoformat().replace("T", " "),
            distinct_id=user,
            first_url="https://example.io/home",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=59000,
        )

        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": session_id_active_is_61,
                "$window_id": str(uuid4()),
            },
        )
        produce_replay_summary(
            session_id=session_id_active_is_61,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=59)),
            distinct_id=user,
            first_url="https://a-different-url.com",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=61000,
        )

        (session_recordings, _, _) = self.filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "having_predicates": '[{"type":"recording","key":"duration","value":60,"operator":"gt"}]',
            }
        )

        assert [(s["session_id"], s["duration"], s["active_seconds"]) for s in session_recordings] == [
            (session_id_total_is_61, 61, 59.0)
        ]

        (session_recordings, _, _) = self.filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "having_predicates": '[{"type":"recording","key":"active_seconds","value":60,"operator":"gt"}]',
            }
        )

        assert [(s["session_id"], s["duration"], s["active_seconds"]) for s in session_recordings] == [
            (session_id_active_is_61, 59, 61.0)
        ]

    @also_test_with_materialized_columns(["$current_url", "$browser"])
    @snapshot_clickhouse_queries
    def test_event_filter_with_properties(self):
        user = "test_event_filter_with_properties-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        session_id_one = f"test_event_filter_with_properties-{str(uuid4())}"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago,
            properties={
                "$browser": "Chrome",
                "$session_id": session_id_one,
                "$window_id": str(uuid4()),
            },
        )
        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago,
            event_name="a_different_event",
            properties={
                "$browser": "Safari",
                "$session_id": session_id_one,
                "$window_id": str(uuid4()),
            },
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        self.assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "properties": [
                            {
                                "key": "$browser",
                                "value": ["Chrome"],
                                "operator": "exact",
                                "type": "event",
                            }
                        ],
                    }
                ]
            },
            [session_id_one],
        )

        self.assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "properties": [
                            {
                                "key": "$browser",
                                "value": ["Firefox"],
                                "operator": "exact",
                                "type": "event",
                            }
                        ],
                    }
                ]
            },
            [],
        )

        self.assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "a_different_event",
                        "type": "events",
                        "order": 0,
                        "name": "a_different_event",
                        "properties": [
                            {
                                "key": "$browser",
                                "value": ["Chrome"],
                                "operator": "exact",
                                "type": "event",
                            }
                        ],
                    }
                ]
            },
            [],
        )

        self.assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "a_different_event",
                        "type": "events",
                        "order": 0,
                        "name": "a_different_event",
                        "properties": [
                            {
                                "key": "$browser",
                                "value": ["Safari"],
                                "operator": "exact",
                                "type": "event",
                            }
                        ],
                    }
                ]
            },
            [session_id_one],
        )

    @snapshot_clickhouse_queries
    def test_multiple_event_filters(self):
        session_id = f"test_multiple_event_filters-{str(uuid4())}"
        user = "test_multiple_event_filters-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )

        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago,
            properties={"$session_id": session_id, "$window_id": "1", "foo": "bar"},
        )
        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago,
            properties={"$session_id": session_id, "$window_id": "1", "bar": "foo"},
        )
        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago,
            properties={"$session_id": session_id, "$window_id": "1", "bar": "foo"},
            event_name="new-event",
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        self.assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    },
                    {
                        "id": "new-event",
                        "type": "events",
                        "order": 0,
                        "name": "new-event",
                    },
                ]
            },
            [session_id],
        )

        self.assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    },
                    {
                        "id": "new-event2",
                        "type": "events",
                        "order": 0,
                        "name": "new-event2",
                    },
                ]
            },
            [],
        )

        # it uses hasAny instead of hasAll because of the OR filter
        self.assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    },
                    {
                        "id": "new-event2",
                        "type": "events",
                        "order": 0,
                        "name": "new-event2",
                    },
                ],
                "operand": "OR",
            },
            [session_id],
        )

        # two events with the same name
        self.assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "name": "$pageview",
                        "properties": [{"key": "foo", "value": ["bar"], "operator": "exact", "type": "event"}],
                    },
                    {
                        "id": "$pageview",
                        "type": "events",
                        "name": "$pageview",
                        "properties": [{"key": "bar", "value": ["foo"], "operator": "exact", "type": "event"}],
                    },
                ],
                "operand": "AND",
            },
            [session_id],
        )

        # two events with different names
        self.assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "name": "$pageview",
                        "properties": [{"key": "foo", "value": ["bar"], "operator": "exact", "type": "event"}],
                    },
                    {
                        "id": "new-event",
                        "type": "events",
                        "name": "new-event",
                        "properties": [{"key": "foo", "value": ["bar"], "operator": "exact", "type": "event"}],
                    },
                ],
                "operand": "AND",
            },
            [],
        )

        # two events with different names
        self.assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "name": "$pageview",
                        "properties": [{"key": "foo", "value": ["bar"], "operator": "exact", "type": "event"}],
                    },
                    {
                        "id": "new-event",
                        "type": "events",
                        "name": "new-event",
                        "properties": [{"key": "foo", "value": ["bar"], "operator": "exact", "type": "event"}],
                    },
                ],
                "operand": "OR",
            },
            [session_id],
        )

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(["$session_id", "$browser"], person_properties=["email"])
    @freeze_time("2023-01-04")
    def test_action_filter(self):
        user = "test_action_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        session_id_one = f"test_action_filter-session-one"
        window_id = "test_action_filter-window-id"
        action_with_properties = self.create_action(
            "custom-event",
            properties=[
                {"key": "$browser", "value": "Firefox"},
                {"key": "$session_id", "value": session_id_one},
                {"key": "$window_id", "value": window_id},
            ],
        )
        action_without_properties = self.create_action(
            name="custom-event",
            properties=[
                {"key": "$session_id", "value": session_id_one},
                {"key": "$window_id", "value": window_id},
            ],
        )

        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago,
            event_name="custom-event",
            properties={
                "$browser": "Chrome",
                "$session_id": session_id_one,
                "$window_id": window_id,
            },
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        self.assert_query_matches_session_ids(
            {
                "actions": [
                    {
                        "id": action_with_properties.id,
                        "type": "actions",
                        "order": 1,
                        "name": "custom-event",
                    }
                ]
            },
            [],
        )

        self.assert_query_matches_session_ids(
            {
                "actions": [
                    {
                        "id": action_without_properties.id,
                        "type": "actions",
                        "order": 1,
                        "name": "custom-event",
                    }
                ]
            },
            [session_id_one],
        )

        # Adding properties to an action
        self.assert_query_matches_session_ids(
            {
                "actions": [
                    {
                        "id": action_without_properties.id,
                        "type": "actions",
                        "order": 1,
                        "name": "custom-event",
                        "properties": [
                            {
                                "key": "$browser",
                                "value": ["Firefox"],
                                "operator": "exact",
                                "type": "event",
                            }
                        ],
                    }
                ]
            },
            [],
        )

        # Adding matching properties to an action
        self.assert_query_matches_session_ids(
            {
                "actions": [
                    {
                        "id": action_without_properties.id,
                        "type": "actions",
                        "order": 1,
                        "name": "custom-event",
                        "properties": [
                            {
                                "key": "$browser",
                                "value": ["Chrome"],
                                "operator": "exact",
                                "type": "event",
                            }
                        ],
                    }
                ]
            },
            [session_id_one],
        )

    def test_event_filter_with_matching_on_session_id(self):
        user_distinct_id = "test_event_filter_with_matching_on_session_id-user"
        Person.objects.create(team=self.team, distinct_ids=[user_distinct_id], properties={"email": "bla"})
        session_id = f"test_event_filter_with_matching_on_session_id-1-{str(uuid4())}"

        create_event(
            team=self.team,
            distinct_id=user_distinct_id,
            timestamp=self.an_hour_ago,
            event_name="$pageview",
            properties={"$session_id": session_id},
        )
        create_event(
            team=self.team,
            distinct_id=user_distinct_id,
            timestamp=self.an_hour_ago,
            event_name="$autocapture",
            properties={"$session_id": str(uuid4())},
        )

        produce_replay_summary(
            distinct_id=user_distinct_id,
            session_id=session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=user_distinct_id,
            session_id=session_id,
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        self.assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ]
            },
            [session_id],
        )

        self.assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$autocapture",
                        "type": "events",
                        "order": 0,
                        "name": "$autocapture",
                    }
                ]
            },
            [],
        )

    @also_test_with_materialized_columns(event_properties=["$current_url", "$browser"], person_properties=["email"])
    @snapshot_clickhouse_queries
    def test_any_event_filter_with_properties(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

        page_view_session_id = f"pageview-session-{str(uuid4())}"
        my_custom_event_session_id = f"my-custom-event-session-{str(uuid4())}"
        non_matching__event_session_id = f"non-matching-event-session-{str(uuid4())}"

        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$browser": "Chrome",
                "$session_id": page_view_session_id,
                "$window_id": "1",
            },
            event_name="$pageview",
        )

        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$browser": "Chrome",
                "$session_id": my_custom_event_session_id,
                "$window_id": "1",
            },
            event_name="my-custom-event",
        )

        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$browser": "Safari",
                "$session_id": non_matching__event_session_id,
                "$window_id": "1",
            },
            event_name="my-non-matching-event",
        )

        produce_replay_summary(
            distinct_id="user",
            session_id=page_view_session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=my_custom_event_session_id,
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=non_matching__event_session_id,
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        self.assert_query_matches_session_ids(
            {
                "events": [
                    {
                        # an id of null means "match any event"
                        "id": None,
                        "type": "events",
                        "order": 0,
                        "name": "All events",
                        "properties": [],
                    }
                ]
            },
            [
                my_custom_event_session_id,
                non_matching__event_session_id,
                page_view_session_id,
            ],
        )

        self.assert_query_matches_session_ids(
            {
                "events": [
                    {
                        # an id of null means "match any event"
                        "id": None,
                        "type": "events",
                        "order": 0,
                        "name": "All events",
                        "properties": [
                            {
                                "key": "$browser",
                                "value": ["Chrome"],
                                "operator": "exact",
                                "type": "event",
                            }
                        ],
                    }
                ]
            },
            [
                my_custom_event_session_id,
                page_view_session_id,
            ],
        )

        self.assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": None,
                        "type": "events",
                        "order": 0,
                        "name": "All events",
                        "properties": [
                            {
                                "key": "$browser",
                                "value": ["Firefox"],
                                "operator": "exact",
                                "type": "event",
                            }
                        ],
                    }
                ]
            },
            [],
        )

    def test_can_filter_for_two_is_not_event_properties(self) -> None:
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )

        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "1",
                "$window_id": "1",
                "probe-one": "val",
                "probe-two": "val",
            },
        )

        produce_replay_summary(
            distinct_id="user",
            session_id="3",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "3",
                "$window_id": "1",
                "probe-one": "something-else",
                "probe-two": "something-else",
            },
        )

        produce_replay_summary(
            distinct_id="user",
            session_id="4",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "4",
                "$window_id": "1",
                "$feature/target-flag-2": False,
                # neither prop present
            },
        )

        self.assert_query_matches_session_ids(
            {
                "properties": [
                    {"type": "event", "key": "probe-one", "operator": "is_not", "value": ["val"]},
                    {"type": "event", "key": "probe-two", "operator": "is_not", "value": ["val"]},
                ]
            },
            ["3", "4"],
        )

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_can_filter_for_does_not_match_regex_event_properties(self) -> None:
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "1",
                "$window_id": "1",
                "$host": "google.com",
            },
        )

        produce_replay_summary(
            distinct_id="user",
            session_id="3",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "3",
                "$window_id": "1",
                "$host": "localhost:3000",
            },
        )

        produce_replay_summary(
            distinct_id="user",
            session_id="4",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "4",
                "$window_id": "1",
                # no host
            },
        )

        self.assert_query_matches_session_ids(
            {
                "properties": [
                    {
                        "key": "$host",
                        "value": "^(localhost|127\\.0\\.0\\.1)($|:)",
                        "operator": "not_regex",
                        "type": "event",
                    },
                ]
            },
            ["1", "4"],
        )

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_can_filter_for_does_not_contain_event_properties(self) -> None:
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

        paul_google_session = str(uuid7())
        produce_replay_summary(
            distinct_id="user",
            session_id=paul_google_session,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago + timedelta(minutes=1),
            properties={
                "$session_id": paul_google_session,
                "$window_id": str(uuid7()),
                "something": "paul@google.com",
                "has": "paul@google.com",
            },
        )

        paul_paul_session = str(uuid7())
        produce_replay_summary(
            distinct_id="user",
            session_id=paul_paul_session,
            first_timestamp=self.an_hour_ago + timedelta(minutes=2),
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago + timedelta(minutes=3),
            properties={
                "$session_id": paul_paul_session,
                "$window_id": str(uuid7()),
                "something": "paul@paul.com",
                "has": "paul@paul.com",
            },
        )

        no_email_session = str(uuid7())
        produce_replay_summary(
            distinct_id="user",
            session_id=no_email_session,
            first_timestamp=self.an_hour_ago + timedelta(minutes=4),
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago + timedelta(minutes=5),
            properties={
                "$session_id": no_email_session,
                "$window_id": str(uuid7()),
                "has": "no something",
                # no something
            },
        )

        self.assert_query_matches_session_ids(
            {
                "properties": [
                    {
                        "key": "something",
                        "value": "paul.com",
                        "operator": "not_icontains",
                        "type": "event",
                    },
                ]
            },
            [paul_google_session, no_email_session],
        )
