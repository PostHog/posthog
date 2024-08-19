from datetime import datetime
from uuid import uuid4

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.log_entries import TRUNCATE_LOG_ENTRIES_TABLE_SQL
from posthog.constants import AvailableFeature
from posthog.models import Cohort, GroupTypeMapping, Person
from posthog.models.action import Action
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.group.util import create_group
from posthog.models.team import Team
from posthog.session_recordings.queries.session_recording_list_from_filters import (
    SessionRecordingListFromFilters,
    SessionRecordingQueryResult,
)
from posthog.session_recordings.queries.session_replay_events import ttl_days
from posthog.session_recordings.queries.test.session_replay_sql import (
    produce_replay_summary,
)
from posthog.session_recordings.sql.session_replay_event_sql import (
    TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    also_test_with_materialized_columns,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)


@freeze_time("2021-01-01T13:46:23")
class TestSessionRecordingsListFromFilters(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())
        sync_execute(TRUNCATE_LOG_ENTRIES_TABLE_SQL)

    def create_action(self, name, team_id=None, properties=None):
        if team_id is None:
            team_id = self.team.pk
        if properties is None:
            properties = []
        action = Action.objects.create(
            team_id=team_id,
            name=name,
            steps_json=[
                {
                    "event": name,
                    "properties": properties,
                }
            ],
        )
        return action

    def create_event(
        self,
        distinct_id,
        timestamp,
        team=None,
        event_name="$pageview",
        properties=None,
    ):
        if team is None:
            team = self.team
        if properties is None:
            properties = {"$os": "Windows 95", "$current_url": "aloha.com/2"}
        return _create_event(
            team=team,
            event=event_name,
            timestamp=timestamp,
            distinct_id=distinct_id,
            properties=properties,
        )

    def _filter_recordings_by(self, recordings_filter: dict) -> SessionRecordingQueryResult:
        the_filter = SessionRecordingsFilter(team=self.team, data=recordings_filter)
        session_recording_list_instance = SessionRecordingListFromFilters(
            filter=the_filter, team=self.team, hogql_query_modifiers=None
        )
        return session_recording_list_instance.run()

    @property
    def an_hour_ago(self):
        return (now() - relativedelta(hours=1)).replace(microsecond=0, second=0)

    @snapshot_clickhouse_queries
    def test_basic_query(self):
        user = "test_basic_query-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id_one = f"test_basic_query-{str(uuid4())}"
        session_id_two = f"test_basic_query-{str(uuid4())}"

        produce_replay_summary(
            session_id=session_id_one,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp=self.an_hour_ago.isoformat().replace("T", " "),
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=20)).isoformat().replace("T", " "),
            distinct_id=user,
            first_url="https://example.io/home",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=50 * 1000 * 0.5,  # 50% of the total expected duration
        )

        produce_replay_summary(
            session_id=session_id_one,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp=(self.an_hour_ago + relativedelta(seconds=10)),
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=50)),
            distinct_id=user,
            first_url="https://a-different-url.com",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=0,  # 30% of the total expected duration
        )

        produce_replay_summary(
            session_id=session_id_two,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp=(self.an_hour_ago + relativedelta(seconds=20)),
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=2000)),
            distinct_id=user,
            first_url="https://another-url.com",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=1980 * 1000 * 0.4,  # 40% of the total expected duration
        )

        session_recordings, more_recordings_available, _ = self._filter_recordings_by({"no_filter": None})

        assert session_recordings == [
            {
                "session_id": session_id_two,
                "team_id": self.team.pk,
                "distinct_id": user,
                "click_count": 2,
                "keypress_count": 2,
                "mouse_activity_count": 2,
                "duration": 1980,
                "active_seconds": 792.0,
                "inactive_seconds": 1188.0,
                "start_time": self.an_hour_ago + relativedelta(seconds=20),
                "end_time": self.an_hour_ago + relativedelta(seconds=2000),
                "first_url": "https://another-url.com",
                "console_log_count": 0,
                "console_warn_count": 0,
                "console_error_count": 0,
            },
            {
                "session_id": session_id_one,
                "team_id": self.team.pk,
                "distinct_id": user,
                "click_count": 4,
                "keypress_count": 4,
                "mouse_activity_count": 4,
                "duration": 50,
                "active_seconds": 25.0,
                "inactive_seconds": 25.0,
                "start_time": self.an_hour_ago,
                "end_time": self.an_hour_ago + relativedelta(seconds=50),
                "first_url": "https://example.io/home",
                "console_log_count": 0,
                "console_warn_count": 0,
                "console_error_count": 0,
            },
        ]

        assert more_recordings_available is False

    @snapshot_clickhouse_queries
    def test_basic_query_active_sessions(
        self,
    ):
        user = "test_basic_query-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id_total_is_61 = f"test_basic_query_active_sessions-total-{str(uuid4())}"
        session_id_active_is_61 = f"test_basic_query_active_sessions-active-{str(uuid4())}"
        session_id_inactive_is_61 = f"test_basic_query_active_sessions-inactive-{str(uuid4())}"

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

        produce_replay_summary(
            session_id=session_id_inactive_is_61,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=61)),
            distinct_id=user,
            first_url="https://a-different-url.com",
            click_count=0,
            keypress_count=0,
            mouse_activity_count=0,
            active_milliseconds=0,
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "having_predicates": '[{"type":"recording","key":"duration","value":60,"operator":"gt"}]',
            }
        )

        assert sorted(
            [(s["session_id"], s["duration"], s["active_seconds"]) for s in session_recordings],
            key=lambda x: x[0],
        ) == [
            (session_id_inactive_is_61, 61, 0.0),
            (session_id_total_is_61, 61, 59.0),
        ]

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "having_predicates": '[{"type":"recording","key":"active_seconds","value":"60","operator":"gt"}]',
            }
        )

        assert [(s["session_id"], s["duration"], s["active_seconds"]) for s in session_recordings] == [
            (session_id_active_is_61, 59, 61.0)
        ]

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "having_predicates": '[{"type":"recording","key":"inactive_seconds","value":"60","operator":"gt"}]',
            }
        )

        assert [(s["session_id"], s["duration"], s["inactive_seconds"]) for s in session_recordings] == [
            (session_id_inactive_is_61, 61, 61.0)
        ]

    @snapshot_clickhouse_queries
    def test_basic_query_with_paging(self):
        user = "test_basic_query_with_paging-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id_one = f"id_one_test_basic_query_with_paging-{str(uuid4())}"
        session_id_two = f"id_two_test_basic_query_with_paging-{str(uuid4())}"

        produce_replay_summary(
            session_id=session_id_one,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp=self.an_hour_ago.isoformat().replace("T", " "),
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=20)).isoformat().replace("T", " "),
            distinct_id=user,
            first_url="https://example.io/home",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=50 * 1000 * 0.5,  # 50% of the total expected duration
        )

        produce_replay_summary(
            session_id=session_id_one,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp=(self.an_hour_ago + relativedelta(seconds=10)),
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=50)),
            distinct_id=user,
            first_url="https://a-different-url.com",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=0,  # 30% of the total expected duration
        )

        produce_replay_summary(
            session_id=session_id_two,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp=(self.an_hour_ago + relativedelta(seconds=20)),
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=2000)),
            distinct_id=user,
            first_url="https://another-url.com",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=1980 * 1000 * 0.4,  # 40% of the total expected duration
        )

        (session_recordings, more_recordings_available, _) = self._filter_recordings_by(
            {"no_filter": None, "limit": 1, "offset": 0}
        )

        assert session_recordings == [
            {
                "session_id": session_id_two,
                "team_id": self.team.pk,
                "distinct_id": user,
                "click_count": 2,
                "keypress_count": 2,
                "mouse_activity_count": 2,
                "duration": 1980,
                "active_seconds": 792.0,
                "inactive_seconds": 1188.0,
                "start_time": self.an_hour_ago + relativedelta(seconds=20),
                "end_time": self.an_hour_ago + relativedelta(seconds=2000),
                "first_url": "https://another-url.com",
                "console_log_count": 0,
                "console_warn_count": 0,
                "console_error_count": 0,
            }
        ]

        assert more_recordings_available is True

        (session_recordings, more_recordings_available, _) = self._filter_recordings_by(
            {"no_filter": None, "limit": 1, "offset": 1}
        )

        assert session_recordings == [
            {
                "session_id": session_id_one,
                "team_id": self.team.pk,
                "distinct_id": user,
                "click_count": 4,
                "keypress_count": 4,
                "mouse_activity_count": 4,
                "duration": 50,
                "active_seconds": 25.0,
                "inactive_seconds": 25.0,
                "start_time": self.an_hour_ago,
                "end_time": self.an_hour_ago + relativedelta(seconds=50),
                "first_url": "https://example.io/home",
                "console_log_count": 0,
                "console_warn_count": 0,
                "console_error_count": 0,
            },
        ]

        assert more_recordings_available is False

        (session_recordings, more_recordings_available, _) = self._filter_recordings_by(
            {"no_filter": None, "limit": 1, "offset": 2}
        )

        assert session_recordings == []

        assert more_recordings_available is False

    @snapshot_clickhouse_queries
    def test_basic_query_with_ordering(self):
        user = "test_basic_query_with_ordering-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id_one = f"test_basic_query_with_ordering-session-1-{str(uuid4())}"
        session_id_two = f"test_basic_query_with_ordering-session-2-{str(uuid4())}"

        session_one_start = self.an_hour_ago + relativedelta(seconds=10)
        produce_replay_summary(
            session_id=session_id_one,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp=session_one_start,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=50)),
            distinct_id=user,
            console_error_count=1000,
            active_milliseconds=1,  # most errors, but the least activity
        )

        produce_replay_summary(
            session_id=session_id_one,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp=session_one_start,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=50)),
            distinct_id=user,
            console_error_count=12,
            active_milliseconds=1,  # most errors, but the least activity
        )

        session_two_start = self.an_hour_ago
        produce_replay_summary(
            session_id=session_id_two,
            team_id=self.team.pk,
            # starts before session one
            first_timestamp=session_two_start,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=50)),
            distinct_id=user,
            console_error_count=430,
            active_milliseconds=1000,  # most activity, but the least errors
        )

        (session_recordings) = self._filter_recordings_by(
            {"no_filter": None, "limit": 3, "offset": 0, "order": "active_seconds"}
        )

        ordered_by_activity = [(r["session_id"], r["active_seconds"]) for r in session_recordings.results]
        assert ordered_by_activity == [(session_id_two, 1.0), (session_id_one, 0.002)]

        (session_recordings) = self._filter_recordings_by(
            {"no_filter": None, "limit": 3, "offset": 0, "order": "console_error_count"}
        )

        ordered_by_errors = [(r["session_id"], r["console_error_count"]) for r in session_recordings.results]
        assert ordered_by_errors == [(session_id_one, 1012), (session_id_two, 430)]

        (session_recordings) = self._filter_recordings_by(
            {"no_filter": None, "limit": 3, "offset": 0, "order": "start_time"}
        )

        ordered_by_default = [(r["session_id"], r["start_time"]) for r in session_recordings.results]
        assert ordered_by_default == [(session_id_one, session_one_start), (session_id_two, session_two_start)]

    def test_first_url_selection(self):
        user = "test_first_url_selection-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id_one = f"first-url-on-first-event-{str(uuid4())}"
        session_id_two = f"first-url-not-on-first-event-{str(uuid4())}"
        session_id_three = f"no-url-from-many-{str(uuid4())}"
        session_id_four = f"events-inserted-out-of-order-{str(uuid4())}"

        # session one has the first url on the first event
        produce_replay_summary(
            session_id=session_id_one,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp=self.an_hour_ago,
            last_timestamp=self.an_hour_ago + relativedelta(seconds=20),
            first_url="https://on-first-event.com",
        )

        produce_replay_summary(
            session_id=session_id_one,
            team_id=self.team.pk,
            first_timestamp=self.an_hour_ago + relativedelta(seconds=10),
            last_timestamp=self.an_hour_ago + relativedelta(seconds=20),
            first_url="https://on-second-event.com",
        )

        produce_replay_summary(
            session_id=session_id_one,
            team_id=self.team.pk,
            first_timestamp=self.an_hour_ago + relativedelta(seconds=20),
            last_timestamp=self.an_hour_ago + relativedelta(seconds=40),
            first_url="https://on-third-event.com",
        )

        # session two has no URL on the first event
        produce_replay_summary(
            session_id=session_id_two,
            team_id=self.team.pk,
            first_timestamp=(self.an_hour_ago + relativedelta(seconds=10)),
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=50)),
            first_url=None,
        )

        produce_replay_summary(
            session_id=session_id_two,
            team_id=self.team.pk,
            first_timestamp=(self.an_hour_ago + relativedelta(seconds=20)),
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            first_url="https://first-is-on-second-event.com",
        )

        produce_replay_summary(
            session_id=session_id_two,
            team_id=self.team.pk,
            first_timestamp=(self.an_hour_ago + relativedelta(seconds=25)),
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            first_url="https://another-on-the-session.com",
        )

        # session three has no URLs
        produce_replay_summary(
            session_id=session_id_three,
            team_id=self.team.pk,
            first_timestamp=self.an_hour_ago,
            last_timestamp=self.an_hour_ago + relativedelta(seconds=50),
            distinct_id=user,
            first_url=None,
        )

        produce_replay_summary(
            session_id=session_id_three,
            team_id=self.team.pk,
            first_timestamp=(self.an_hour_ago + relativedelta(seconds=10)),
            last_timestamp=self.an_hour_ago + relativedelta(seconds=50),
            distinct_id=user,
            first_url=None,
        )

        produce_replay_summary(
            session_id=session_id_three,
            team_id=self.team.pk,
            first_timestamp=(self.an_hour_ago + relativedelta(seconds=20)),
            last_timestamp=self.an_hour_ago + relativedelta(seconds=60),
            distinct_id=user,
            first_url=None,
        )

        # session four events are received out of order
        produce_replay_summary(
            session_id=session_id_four,
            team_id=self.team.pk,
            first_timestamp=self.an_hour_ago + relativedelta(seconds=20),
            last_timestamp=self.an_hour_ago + relativedelta(seconds=25),
            first_url="https://on-first-received-event.com",
        )
        produce_replay_summary(
            session_id=session_id_four,
            team_id=self.team.pk,
            first_timestamp=self.an_hour_ago + relativedelta(seconds=10),
            last_timestamp=self.an_hour_ago + relativedelta(seconds=25),
            first_url="https://on-second-received-event-but-actually-first.com",
        )

        session_recordings, more_recordings_available, _ = self._filter_recordings_by({"no_filter": None})

        assert sorted(
            [{"session_id": r["session_id"], "first_url": r["first_url"]} for r in session_recordings],
            key=lambda x: x["session_id"],
        ) == sorted(
            [
                {
                    "session_id": session_id_one,
                    "first_url": "https://on-first-event.com",
                },
                {
                    "session_id": session_id_two,
                    "first_url": "https://first-is-on-second-event.com",
                },
                {
                    "session_id": session_id_three,
                    "first_url": None,
                },
                {
                    "session_id": session_id_four,
                    "first_url": "https://on-second-received-event-but-actually-first.com",
                },
            ],
            # mypy unhappy about this lambda when first_url can be None 🤷️
            key=lambda x: x["session_id"],  # type: ignore
        )

    def test_recordings_dont_leak_data_between_teams(self):
        another_team = Team.objects.create(organization=self.organization)
        user = "test_recordings_dont_leak_data_between_teams-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        Person.objects.create(team=another_team, distinct_ids=[user], properties={"email": "bla"})

        session_id_one = f"test_recordings_dont_leak_data_between_teams-1-{str(uuid4())}"
        session_id_two = f"test_recordings_dont_leak_data_between_teams-2-{str(uuid4())}"

        produce_replay_summary(
            session_id=session_id_one,
            team_id=another_team.pk,
            distinct_id=user,
            first_timestamp=self.an_hour_ago,
            last_timestamp=self.an_hour_ago + relativedelta(seconds=20),
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=20 * 1000 * 0.5,  # 50% of the total expected duration
        )

        produce_replay_summary(
            session_id=session_id_two,
            team_id=self.team.pk,
            distinct_id=user,
            first_timestamp=self.an_hour_ago,
            last_timestamp=self.an_hour_ago + relativedelta(seconds=20),
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=20 * 1000 * 0.5,  # 50% of the total expected duration
        )

        (session_recordings, _, _) = self._filter_recordings_by({"no_filter": None})

        assert [{"session": r["session_id"], "user": r["distinct_id"]} for r in session_recordings] == [
            {"session": session_id_two, "user": user}
        ]

    @snapshot_clickhouse_queries
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
        self.create_event(
            user,
            self.an_hour_ago,
            properties={"$session_id": session_id_one, "$window_id": str(uuid4())},
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ]
            }
        )

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id_one

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$autocapture",
                        "type": "events",
                        "order": 0,
                        "name": "$autocapture",
                    }
                ]
            }
        )
        assert session_recordings == []

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
        self.create_event(
            user,
            self.an_hour_ago - relativedelta(days=SessionRecordingListFromFilters.SESSION_RECORDINGS_DEFAULT_LIMIT + 1),
            properties={"$session_id": session_id_one, "$window_id": str(uuid4())},
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ]
            }
        )
        assert len(session_recordings) == 0

        (session_recordings, _, _) = self._filter_recordings_by({})
        # without an event filter the recording is present, showing that the TTL was applied to the events table too
        # we want this to limit the amount of event data we query
        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id_one

    @snapshot_clickhouse_queries
    def test_ttl_days(self):
        assert ttl_days(self.team) == 21

        with self.is_cloud(True):
            # Far enough in the future from `days_since_blob_ingestion` but not paid
            with freeze_time("2023-09-01T12:00:01Z"):
                assert ttl_days(self.team) == 30

            self.team.organization.available_product_features = [
                {"key": AvailableFeature.RECORDINGS_PLAYLISTS, "name": AvailableFeature.RECORDINGS_PLAYLISTS}
            ]

            # Far enough in the future from `days_since_blob_ingestion` but paid
            with freeze_time("2023-12-01T12:00:01Z"):
                assert ttl_days(self.team) == 90

            # Not far enough in the future from `days_since_blob_ingestion`
            with freeze_time("2023-09-05T12:00:01Z"):
                assert ttl_days(self.team) == 35

    @snapshot_clickhouse_queries
    def test_filter_on_session_ids(self):
        user = "test_session_ids-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        first_session_id = str(uuid4())
        second_session_id = str(uuid4())
        third_session_id = str(uuid4())

        produce_replay_summary(
            session_id=first_session_id,
            team_id=self.team.pk,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(minutes=5)),
            distinct_id=user,
            first_url="https://example.io/home",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=59000,
        )

        produce_replay_summary(
            session_id=second_session_id,
            team_id=self.team.pk,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(minutes=1)),
            distinct_id=user,
            first_url="https://example.io/home",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=61000,
        )

        produce_replay_summary(
            session_id=third_session_id,
            team_id=self.team.pk,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(minutes=10)),
            distinct_id=user,
            first_url="https://example.io/home",
            click_count=0,
            keypress_count=0,
            mouse_activity_count=0,
            active_milliseconds=0,
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "session_ids": [first_session_id],
            }
        )

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == first_session_id

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "session_ids": [first_session_id, second_session_id],
            }
        )

        assert sorted([s["session_id"] for s in session_recordings]) == sorted(
            [
                first_session_id,
                second_session_id,
            ]
        )

    @snapshot_clickhouse_queries
    def test_event_filter_with_active_sessions(
        self,
    ):
        user = "test_basic_query-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id_total_is_61 = f"test_basic_query_active_sessions-total-{str(uuid4())}"
        session_id_active_is_61 = f"test_basic_query_active_sessions-active-{str(uuid4())}"

        self.create_event(
            user,
            self.an_hour_ago,
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

        self.create_event(
            user,
            self.an_hour_ago,
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

        (session_recordings, _, _) = self._filter_recordings_by(
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

        (session_recordings, _, _) = self._filter_recordings_by(
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
        self.create_event(
            user,
            self.an_hour_ago,
            properties={
                "$browser": "Chrome",
                "$session_id": session_id_one,
                "$window_id": str(uuid4()),
            },
        )
        self.create_event(
            user,
            self.an_hour_ago,
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

        (session_recordings, _, _) = self._filter_recordings_by(
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
            }
        )
        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id_one

        (session_recordings, _, _) = self._filter_recordings_by(
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
            }
        )
        assert session_recordings == []

        (session_recordings, _, _) = self._filter_recordings_by(
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
            }
        )
        assert len(session_recordings) == 0

        (session_recordings, _, _) = self._filter_recordings_by(
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
            }
        )
        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id_one

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

        self.create_event(
            user,
            self.an_hour_ago,
            properties={"$session_id": session_id, "$window_id": "1"},
        )
        self.create_event(
            user,
            self.an_hour_ago,
            properties={"$session_id": session_id, "$window_id": "1"},
            event_name="new-event",
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        (session_recordings, _, _) = self._filter_recordings_by(
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
            }
        )

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id

        (session_recordings, _, _) = self._filter_recordings_by(
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
            }
        )
        assert session_recordings == []

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
        self.create_event(
            user,
            self.an_hour_ago,
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

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "actions": [
                    {
                        "id": action_with_properties.id,
                        "type": "actions",
                        "order": 1,
                        "name": "custom-event",
                    }
                ]
            }
        )
        assert session_recordings == []

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "actions": [
                    {
                        "id": action_without_properties.id,
                        "type": "actions",
                        "order": 1,
                        "name": "custom-event",
                    }
                ]
            }
        )

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id_one

        # Adding properties to an action
        (session_recordings, _, _) = self._filter_recordings_by(
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
            }
        )
        assert session_recordings == []

        # Adding matching properties to an action
        (session_recordings, _, _) = self._filter_recordings_by(
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
            }
        )

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id_one

    def test_all_sessions_recording_object_keys_with_entity_filter(self):
        user = "test_all_sessions_recording_object_keys_with_entity_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        session_id = f"test_all_sessions_recording_object_keys_with_entity_filter-{str(uuid4())}"
        window_id = str(uuid4())

        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=60)),
            team_id=self.team.id,
            first_url="https://recieved-out-of-order.com/second",
        )
        self.create_event(
            user,
            self.an_hour_ago,
            properties={"$session_id": session_id, "$window_id": window_id},
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
            first_url="https://recieved-out-of-order.com/first",
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ]
            }
        )

        assert session_recordings == [
            {
                "session_id": session_id,
                "distinct_id": user,
                "duration": 60,
                "start_time": self.an_hour_ago,
                "end_time": self.an_hour_ago + relativedelta(seconds=60),
                "active_seconds": 0.0,
                "click_count": 0,
                "first_url": "https://recieved-out-of-order.com/first",
                "inactive_seconds": 60.0,
                "keypress_count": 0,
                "mouse_activity_count": 0,
                "team_id": self.team.id,
                "console_log_count": 0,
                "console_warn_count": 0,
                "console_error_count": 0,
            }
        ]

    @snapshot_clickhouse_queries
    def test_duration_filter(self):
        user = "test_duration_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id_one = "session one is 29 seconds long"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=29)),
            team_id=self.team.id,
        )

        session_id_two = "session two is 61 seconds long"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_two,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=61)),
            team_id=self.team.id,
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {"having_predicates": '[{"type":"recording","key":"duration","value":60,"operator":"gt"}]'}
        )
        assert [r["session_id"] for r in session_recordings] == [session_id_two]

        (session_recordings, _, _) = self._filter_recordings_by(
            {"having_predicates": '[{"type":"recording","key":"duration","value":60,"operator":"lt"}]'}
        )
        assert [r["session_id"] for r in session_recordings] == [session_id_one]

    @snapshot_clickhouse_queries
    def test_operand_or_person_filters(self):
        user = "test_operand_or_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "test@posthog.com"})

        second_user = "test_operand_or_filter-second_user"
        Person.objects.create(team=self.team, distinct_ids=[second_user], properties={"email": "david@posthog.com"})

        session_id_one = "session_id_one"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        session_id_two = "session_id_two"
        produce_replay_summary(
            distinct_id=second_user,
            session_id=session_id_two,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "properties": [
                    {
                        "key": "email",
                        "value": ["test@posthog.com"],
                        "operator": "exact",
                        "type": "person",
                    },
                    {
                        "key": "email",
                        "value": ["david@posthog.com"],
                        "operator": "exact",
                        "type": "person",
                    },
                ],
                "operand": "AND",
            }
        )
        assert len(session_recordings) == 0

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "properties": [
                    {
                        "key": "email",
                        "value": ["test@posthog.com"],
                        "operator": "exact",
                        "type": "person",
                    },
                    {
                        "key": "email",
                        "value": ["david@posthog.com"],
                        "operator": "exact",
                        "type": "person",
                    },
                ],
                "operand": "OR",
            }
        )
        assert len(session_recordings) == 2
        assert sorted([r["session_id"] for r in session_recordings]) == sorted([session_id_one, session_id_two])

    @snapshot_clickhouse_queries
    def test_operand_or_event_filters(self):
        user = "test_operand_or_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "test@posthog.com"})

        second_user = "test_operand_or_filter-second_user"
        Person.objects.create(team=self.team, distinct_ids=[second_user], properties={"email": "david@posthog.com"})

        session_id_one = "session_id_one"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )
        self.create_event(
            user,
            self.an_hour_ago + relativedelta(seconds=10),
            properties={"$session_id": session_id_one},
        )

        session_id_two = "session_id_two"
        produce_replay_summary(
            distinct_id=second_user,
            session_id=session_id_two,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )
        self.create_event(
            user,
            self.an_hour_ago + relativedelta(seconds=10),
            event_name="custom_event",
            properties={"$session_id": session_id_two},
        )

        session_id_three = "session_id_three"
        produce_replay_summary(
            distinct_id=second_user,
            session_id=session_id_three,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    },
                    {
                        "id": "custom_event",
                        "type": "events",
                        "order": 0,
                        "name": "custom_event",
                    },
                ],
                "operand": "AND",
            }
        )
        assert len(session_recordings) == 0

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    },
                    {
                        "id": "custom_event",
                        "type": "events",
                        "order": 0,
                        "name": "custom_event",
                    },
                ],
                "operand": "OR",
            }
        )
        assert len(session_recordings) == 2
        assert sorted([r["session_id"] for r in session_recordings]) == sorted([session_id_two, session_id_one])

    @snapshot_clickhouse_queries
    def test_operand_or_filters(self):
        user = "test_operand_or_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_with_both_log_filters = "both_log_filters"
        produce_replay_summary(
            distinct_id="user",
            session_id=session_with_both_log_filters,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            console_warn_count=1,
            log_messages={
                "warn": [
                    "random",
                ],
            },
        )
        session_with_one_log_filter = "one_log_filter"
        produce_replay_summary(
            distinct_id="user",
            session_id=session_with_one_log_filter,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            console_warn_count=1,
            log_messages={
                "warn": [
                    "warn",
                ],
            },
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "console_log_filters": '[{"key": "level", "value": ["warn"], "operator": "exact", "type": "log_entry"}, {"key": "message", "value": "random", "operator": "exact", "type": "log_entry"}]',
                "operand": "AND",
            }
        )
        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_with_both_log_filters

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "console_log_filters": '[{"key": "level", "value": ["warn"], "operator": "exact", "type": "log_entry"}, {"key": "message", "value": "random", "operator": "exact", "type": "log_entry"}]',
                "operand": "OR",
            }
        )
        assert len(session_recordings) == 2

    @snapshot_clickhouse_queries
    def test_operand_or_mandatory_filters(self):
        user = "test_operand_or_filter-user"
        person = Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        second_user = "test_operand_or_filter-second_user"
        second_person = Person.objects.create(team=self.team, distinct_ids=[second_user], properties={"email": "bla"})

        session_id_one = "session_id_one"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )
        self.create_event(
            user,
            self.an_hour_ago + relativedelta(seconds=10),
            properties={"$session_id": session_id_one},
        )

        session_id_two = "session_id_two"
        produce_replay_summary(
            distinct_id=second_user,
            session_id=session_id_two,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        # person or event filter -> person matches, event matches -> returns session
        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "person_uuid": str(person.uuid),
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "operand": "OR",
            }
        )
        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id_one

        # person or event filter -> person does not match, event matches -> does not return session
        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "person_uuid": str(second_person.uuid),
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "operand": "OR",
            }
        )
        assert len(session_recordings) == 0

        # session_id or event filter -> person matches, event matches -> returns session
        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "session_ids": [session_id_one],
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "operand": "OR",
            }
        )
        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id_one

        # session_id or event filter -> person does not match, event matches -> does not return session
        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "session_ids": [session_id_two],
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "operand": "OR",
            }
        )
        assert len(session_recordings) == 0

    @snapshot_clickhouse_queries
    def test_date_from_filter(self):
        user = "test_date_from_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        produce_replay_summary(
            distinct_id=user,
            session_id="three days before base time",
            first_timestamp=(self.an_hour_ago - relativedelta(days=3, seconds=100)),
            last_timestamp=(self.an_hour_ago - relativedelta(days=3)),
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=user,
            session_id="two days before base time",
            first_timestamp=(self.an_hour_ago - relativedelta(days=2, seconds=100)),
            last_timestamp=(self.an_hour_ago - relativedelta(days=2)),
            team_id=self.team.id,
        )

        (session_recordings, _, _) = self._filter_recordings_by({"date_from": self.an_hour_ago.strftime("%Y-%m-%d")})
        assert session_recordings == []

        (session_recordings, _, _) = self._filter_recordings_by(
            {"date_from": (self.an_hour_ago - relativedelta(days=2)).strftime("%Y-%m-%d")}
        )
        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == "two days before base time"

    @snapshot_clickhouse_queries
    def test_date_from_filter_cannot_search_before_ttl(self):
        with freeze_time(self.an_hour_ago):
            user = "test_date_from_filter_cannot_search_before_ttl-user"
            Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

            produce_replay_summary(
                distinct_id=user,
                session_id="storage is past ttl",
                first_timestamp=(self.an_hour_ago - relativedelta(days=22)),
                # an illegally long session but it started 22 days ago
                last_timestamp=(self.an_hour_ago - relativedelta(days=3)),
                team_id=self.team.id,
            )
            produce_replay_summary(
                distinct_id=user,
                session_id="storage is not past ttl",
                first_timestamp=(self.an_hour_ago - relativedelta(days=19)),
                last_timestamp=(self.an_hour_ago - relativedelta(days=2)),
                team_id=self.team.id,
            )

            (session_recordings, _, _) = self._filter_recordings_by(
                {"date_from": (self.an_hour_ago - relativedelta(days=20)).strftime("%Y-%m-%d")}
            )
            assert len(session_recordings) == 1
            assert session_recordings[0]["session_id"] == "storage is not past ttl"

            (session_recordings, _, _) = self._filter_recordings_by(
                {"date_from": (self.an_hour_ago - relativedelta(days=21)).strftime("%Y-%m-%d")}
            )
            assert len(session_recordings) == 1
            assert session_recordings[0]["session_id"] == "storage is not past ttl"

            (session_recordings, _, _) = self._filter_recordings_by(
                {"date_from": (self.an_hour_ago - relativedelta(days=22)).strftime("%Y-%m-%d")}
            )
            assert len(session_recordings) == 1
            assert session_recordings[0]["session_id"] == "storage is not past ttl"

    @snapshot_clickhouse_queries
    def test_date_to_filter(self):
        user = "test_date_to_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        produce_replay_summary(
            distinct_id=user,
            session_id="three days before base time",
            first_timestamp=(self.an_hour_ago - relativedelta(days=3, seconds=100)),
            last_timestamp=(self.an_hour_ago - relativedelta(days=3)),
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=user,
            session_id="two days before base time",
            first_timestamp=(self.an_hour_ago - relativedelta(days=2, seconds=100)),
            last_timestamp=(self.an_hour_ago - relativedelta(days=2)),
            team_id=self.team.id,
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {"date_to": (self.an_hour_ago - relativedelta(days=4)).strftime("%Y-%m-%d")}
        )
        assert session_recordings == []

        (session_recordings, _, _) = self._filter_recordings_by(
            {"date_to": (self.an_hour_ago - relativedelta(days=3)).strftime("%Y-%m-%d")}
        )

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == "three days before base time"

    def test_recording_that_spans_time_bounds(self):
        user = "test_recording_that_spans_time_bounds-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        day_line = datetime(2021, 11, 5)
        session_id = f"session-one-{user}"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=(day_line - relativedelta(hours=3)),
            last_timestamp=(day_line + relativedelta(hours=3)),
            team_id=self.team.id,
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "date_to": day_line.strftime("%Y-%m-%d"),
                "date_from": (day_line - relativedelta(days=10)).strftime("%Y-%m-%d"),
            }
        )

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id
        assert session_recordings[0]["duration"] == 6 * 60 * 60

    @snapshot_clickhouse_queries
    def test_person_id_filter(self):
        three_user_ids = [str(uuid4()) for _ in range(3)]
        session_id_one = f"test_person_id_filter-{str(uuid4())}"
        session_id_two = f"test_person_id_filter-{str(uuid4())}"
        p = Person.objects.create(
            team=self.team,
            distinct_ids=[three_user_ids[0], three_user_ids[1]],
            properties={"email": "bla"},
        )
        produce_replay_summary(
            distinct_id=three_user_ids[0],
            session_id=session_id_one,
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=three_user_ids[1],
            session_id=session_id_two,
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=three_user_ids[2],
            session_id=str(uuid4()),
            team_id=self.team.id,
        )

        (session_recordings, _, _) = self._filter_recordings_by({"person_uuid": str(p.uuid)})
        assert sorted([r["session_id"] for r in session_recordings]) == sorted([session_id_two, session_id_one])

    @snapshot_clickhouse_queries
    def test_all_filters_at_once(self):
        three_user_ids = [str(uuid4()) for _ in range(3)]
        target_session_id = f"test_all_filters_at_once-{str(uuid4())}"

        p = Person.objects.create(
            team=self.team,
            distinct_ids=[three_user_ids[0], three_user_ids[1]],
            properties={"email": "bla"},
        )
        custom_event_action = self.create_action(name="custom-event")

        produce_replay_summary(
            distinct_id=three_user_ids[0],
            session_id=target_session_id,
            first_timestamp=(self.an_hour_ago - relativedelta(days=3)),
            team_id=self.team.id,
        )
        produce_replay_summary(
            # does not match because of user distinct id
            distinct_id=three_user_ids[2],
            session_id=target_session_id,
            first_timestamp=(self.an_hour_ago - relativedelta(days=3)),
            team_id=self.team.id,
        )
        self.create_event(
            three_user_ids[0],
            self.an_hour_ago - relativedelta(days=3),
            properties={"$session_id": target_session_id},
        )
        self.create_event(
            three_user_ids[0],
            self.an_hour_ago - relativedelta(days=3),
            event_name="custom-event",
            properties={"$browser": "Chrome", "$session_id": target_session_id},
        )
        produce_replay_summary(
            distinct_id=three_user_ids[1],
            session_id=target_session_id,
            first_timestamp=(self.an_hour_ago - relativedelta(days=3) + relativedelta(hours=6)),
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=three_user_ids[1],
            # does not match because of session id
            session_id=str(uuid4()),
            first_timestamp=(self.an_hour_ago - relativedelta(days=3) + relativedelta(hours=6)),
            team_id=self.team.id,
        )

        flush_persons_and_events()

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "person_uuid": str(p.uuid),
                "date_to": (self.an_hour_ago + relativedelta(days=3)).strftime("%Y-%m-%d"),
                "date_from": (self.an_hour_ago - relativedelta(days=10)).strftime("%Y-%m-%d"),
                "session_recording_duration": '{"type":"recording","key":"duration","value":60,"operator":"gt"}',
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "actions": [
                    {
                        "id": custom_event_action.id,
                        "type": "actions",
                        "order": 1,
                        "name": "custom-event",
                    }
                ],
            }
        )

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == target_session_id

    def test_teams_dont_leak_event_filter(self):
        user = "test_teams_dont_leak_event_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        another_team = Team.objects.create(organization=self.organization)

        session_id = f"test_teams_dont_leak_event_filter-{str(uuid4())}"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        self.create_event(1, self.an_hour_ago + relativedelta(seconds=15), team=another_team)
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ]
            }
        )
        assert session_recordings == []

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(person_properties=["email"])
    def test_filter_with_person_properties_exact(self):
        session_id_one, session_id_two = self._two_sessions_two_persons(
            "test_filter_with_person_properties_exact",
            session_one_person_properties={"email": "bla@gmail.com"},
            session_two_person_properties={"email": "bla2@hotmail.com"},
        )

        query_results: SessionRecordingQueryResult = self._filter_recordings_by(
            {
                "properties": [
                    {
                        "key": "email",
                        "value": ["bla@gmail.com"],
                        "operator": "exact",
                        "type": "person",
                    }
                ]
            }
        )

        assert [x["session_id"] for x in query_results.results] == [session_id_one]

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(person_properties=["email"])
    def test_filter_with_person_properties_not_contains(self):
        session_id_one, session_id_two = self._two_sessions_two_persons(
            "test_filter_with_person_properties_not_contains",
            session_one_person_properties={"email": "bla@gmail.com"},
            session_two_person_properties={"email": "bla2@hotmail.com"},
        )

        query_results: SessionRecordingQueryResult = self._filter_recordings_by(
            {"properties": [{"key": "email", "value": "gmail.com", "operator": "not_icontains", "type": "person"}]}
        )

        assert [x["session_id"] for x in query_results.results] == [session_id_two]

    def _two_sessions_two_persons(
        self, label: str, session_one_person_properties: dict, session_two_person_properties: dict
    ) -> tuple[str, str]:
        sessions = []

        for i in range(2):
            user = f"{label}-user-{i}"
            session = f"{label}-session-{i}"
            sessions.append(session)

            Person.objects.create(
                team=self.team,
                distinct_ids=[user],
                properties=session_one_person_properties if i == 0 else session_two_person_properties,
            )

            produce_replay_summary(
                distinct_id=user,
                session_id=session,
                first_timestamp=self.an_hour_ago,
                team_id=self.team.id,
            )
            produce_replay_summary(
                distinct_id=user,
                session_id=session,
                first_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
                team_id=self.team.id,
            )

        return sessions[0], sessions[1]

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(person_properties=["$some_prop"])
    def test_filter_with_cohort_properties(self):
        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            with freeze_time("2021-08-21T20:00:00.000Z"):
                user_one = "test_filter_with_cohort_properties-user"
                user_two = "test_filter_with_cohort_properties-user2"
                session_id_one = f"test_filter_with_cohort_properties-1-{str(uuid4())}"
                session_id_two = f"test_filter_with_cohort_properties-2-{str(uuid4())}"

                Person.objects.create(team=self.team, distinct_ids=[user_one], properties={"email": "bla"})
                Person.objects.create(
                    team=self.team,
                    distinct_ids=[user_two],
                    properties={"email": "bla2", "$some_prop": "some_val"},
                )
                cohort = Cohort.objects.create(
                    team=self.team,
                    name="cohort1",
                    groups=[
                        {
                            "properties": [
                                {
                                    "key": "$some_prop",
                                    "value": "some_val",
                                    "type": "person",
                                }
                            ]
                        }
                    ],
                )
                cohort.calculate_people_ch(pending_version=0)

                produce_replay_summary(
                    distinct_id=user_one,
                    session_id=session_id_one,
                    first_timestamp=self.an_hour_ago,
                    team_id=self.team.id,
                )
                # self.create_event(user_one, self.base_time, team=self.team)
                produce_replay_summary(
                    distinct_id=user_one,
                    session_id=session_id_one,
                    first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
                    team_id=self.team.id,
                )
                produce_replay_summary(
                    distinct_id=user_two,
                    session_id=session_id_two,
                    first_timestamp=self.an_hour_ago,
                    team_id=self.team.id,
                )
                # self.create_event(user_two, self.base_time, team=self.team)
                produce_replay_summary(
                    distinct_id=user_two,
                    session_id=session_id_two,
                    first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
                    team_id=self.team.id,
                )

                (session_recordings, _, _) = self._filter_recordings_by(
                    {
                        "properties": [
                            {
                                "key": "id",
                                "value": cohort.pk,
                                "operator": None,
                                "type": "cohort",
                            }
                        ]
                    }
                )

                assert len(session_recordings) == 1
                assert session_recordings[0]["session_id"] == session_id_two

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(person_properties=["$some_prop"])
    def test_filter_with_events_and_cohorts(self):
        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            with freeze_time("2021-08-21T20:00:00.000Z"):
                user_one = "test_filter_with_events_and_cohorts-user"
                user_two = "test_filter_with_events_and_cohorts-user2"
                session_id_one = f"test_filter_with_events_and_cohorts-1-{str(uuid4())}"
                session_id_two = f"test_filter_with_events_and_cohorts-2-{str(uuid4())}"

                Person.objects.create(team=self.team, distinct_ids=[user_one], properties={"email": "bla"})
                Person.objects.create(
                    team=self.team,
                    distinct_ids=[user_two],
                    properties={"email": "bla2", "$some_prop": "some_val"},
                )
                cohort = Cohort.objects.create(
                    team=self.team,
                    name="cohort1",
                    groups=[
                        {
                            "properties": [
                                {
                                    "key": "$some_prop",
                                    "value": "some_val",
                                    "type": "person",
                                }
                            ]
                        }
                    ],
                )
                cohort.calculate_people_ch(pending_version=0)

                produce_replay_summary(
                    distinct_id=user_one,
                    session_id=session_id_one,
                    first_timestamp=self.an_hour_ago,
                    team_id=self.team.id,
                )
                self.create_event(
                    user_one,
                    self.an_hour_ago,
                    team=self.team,
                    event_name="custom_event",
                    properties={"$session_id": session_id_one},
                )
                produce_replay_summary(
                    distinct_id=user_one,
                    session_id=session_id_one,
                    first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
                    team_id=self.team.id,
                )
                produce_replay_summary(
                    distinct_id=user_two,
                    session_id=session_id_two,
                    first_timestamp=self.an_hour_ago,
                    team_id=self.team.id,
                )
                self.create_event(
                    user_two,
                    self.an_hour_ago,
                    team=self.team,
                    event_name="custom_event",
                    properties={"$session_id": session_id_two},
                )
                produce_replay_summary(
                    distinct_id=user_two,
                    session_id=session_id_two,
                    first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
                    team_id=self.team.id,
                )

                (session_recordings, _, _) = self._filter_recordings_by(
                    {
                        # has to be in the cohort and pageview has to be in the events
                        # test data has one user in the cohort but no pageviews
                        "properties": [
                            {
                                "key": "id",
                                "value": cohort.pk,
                                "operator": None,
                                "type": "cohort",
                            }
                        ],
                        "events": [
                            {
                                "id": "$pageview",
                                "type": "events",
                                "order": 0,
                                "name": "$pageview",
                            }
                        ],
                    }
                )

                assert len(session_recordings) == 0

                (session_recordings, _, _) = self._filter_recordings_by(
                    {
                        "properties": [
                            {
                                "key": "id",
                                "value": cohort.pk,
                                "operator": None,
                                "type": "cohort",
                            }
                        ],
                        "events": [
                            {
                                "id": "custom_event",
                                "type": "events",
                                "order": 0,
                                "name": "custom_event",
                            }
                        ],
                    }
                )

                assert len(session_recordings) == 1
                assert session_recordings[0]["session_id"] == session_id_two

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(["$current_url"])
    def test_event_filter_with_matching_on_session_id(self):
        user_distinct_id = "test_event_filter_with_matching_on_session_id-user"
        Person.objects.create(team=self.team, distinct_ids=[user_distinct_id], properties={"email": "bla"})
        session_id = f"test_event_filter_with_matching_on_session_id-1-{str(uuid4())}"

        self.create_event(
            user_distinct_id,
            self.an_hour_ago,
            event_name="$pageview",
            properties={"$session_id": session_id},
        )
        self.create_event(
            user_distinct_id,
            self.an_hour_ago,
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

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ]
            }
        )

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$autocapture",
                        "type": "events",
                        "order": 0,
                        "name": "$autocapture",
                    }
                ]
            }
        )
        assert session_recordings == []

    @also_test_with_materialized_columns(event_properties=["$current_url", "$browser"], person_properties=["email"])
    @snapshot_clickhouse_queries
    def test_event_filter_with_hogql_properties(self):
        user = "test_event_filter_with_hogql_properties-user"

        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id = f"test_event_filter_with_hogql_properties-1-{str(uuid4())}"
        self.create_event(
            user,
            self.an_hour_ago,
            properties={
                "$browser": "Chrome",
                "$session_id": session_id,
                "$window_id": str(uuid4()),
            },
        )

        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "properties": [
                            {"key": "properties.$browser == 'Chrome'", "type": "hogql"},
                        ],
                    }
                ]
            }
        )

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "properties": [{"key": "properties.$browser == 'Firefox'", "type": "hogql"}],
                    }
                ]
            }
        )

        assert session_recordings == []

    @snapshot_clickhouse_queries
    def test_event_filter_with_hogql_person_properties(self):
        user = "test_event_filter_with_hogql_properties-user"

        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id = f"test_event_filter_with_hogql_properties-1-{str(uuid4())}"
        self.create_event(
            user,
            self.an_hour_ago,
            properties={
                "$browser": "Chrome",
                "$session_id": session_id,
                "$window_id": str(uuid4()),
            },
        )

        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "properties": [
                            {
                                "key": "person.properties.email == 'bla'",
                                "type": "hogql",
                            },
                        ],
                    }
                ]
            }
        )

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "properties": [
                            {
                                "key": "person.properties.email == 'something else'",
                                "type": "hogql",
                            },
                        ],
                    }
                ]
            }
        )

        assert session_recordings == []

    @also_test_with_materialized_columns(["$current_url", "$browser"])
    @snapshot_clickhouse_queries
    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_any_event_filter_with_properties(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

        page_view_session_id = f"pageview-session-{str(uuid4())}"
        my_custom_event_session_id = f"my-custom-event-session-{str(uuid4())}"
        non_matching__event_session_id = f"non-matching-event-session-{str(uuid4())}"

        self.create_event(
            "user",
            self.an_hour_ago,
            properties={
                "$browser": "Chrome",
                "$session_id": page_view_session_id,
                "$window_id": "1",
            },
            event_name="$pageview",
        )

        self.create_event(
            "user",
            self.an_hour_ago,
            properties={
                "$browser": "Chrome",
                "$session_id": my_custom_event_session_id,
                "$window_id": "1",
            },
            event_name="my-custom-event",
        )

        self.create_event(
            "user",
            self.an_hour_ago,
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

        (session_recordings, _, _) = self._filter_recordings_by(
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
            }
        )

        assert sorted(
            [sr["session_id"] for sr in session_recordings],
        ) == [
            my_custom_event_session_id,
            non_matching__event_session_id,
            page_view_session_id,
        ]

        (session_recordings, _, _) = self._filter_recordings_by(
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
            }
        )

        assert sorted(
            [sr["session_id"] for sr in session_recordings],
        ) == [
            my_custom_event_session_id,
            page_view_session_id,
        ]

        (session_recordings, _, _) = self._filter_recordings_by(
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
            }
        )
        assert session_recordings == []

    @snapshot_clickhouse_queries
    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_filter_for_recordings_with_console_logs(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

        with_logs_session_id = f"with-logs-session-{str(uuid4())}"
        without_logs_session_id = f"no-logs-session-{str(uuid4())}"

        produce_replay_summary(
            distinct_id="user",
            session_id=with_logs_session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            console_log_count=4,
            log_messages={
                "info": [
                    "info",
                    "info",
                    "info",
                ],
            },
        )

        produce_replay_summary(
            distinct_id="user",
            session_id=without_logs_session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )

        # (session_recordings, _, _) = self._filter_recordings_by({"console_logs": ["info"]})

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "console_log_filters": '[{"key": "level", "value": ["info"], "operator": "exact", "type": "log_entry"}]',
                "operand": "AND",
            }
        )

        actual = sorted(
            [(sr["session_id"], sr["console_log_count"]) for sr in session_recordings],
            key=lambda x: x[0],
        )

        assert actual == [
            (with_logs_session_id, 4),
        ]

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "console_log_filters": '[{"key": "level", "value": ["warn"], "operator": "exact", "type": "log_entry"}]',
                "operand": "AND",
            }
        )
        assert session_recordings == []

    @snapshot_clickhouse_queries
    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_filter_for_recordings_with_console_warns(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

        with_logs_session_id = f"with-logs-session-{str(uuid4())}"
        without_logs_session_id = f"no-logs-session-{str(uuid4())}"

        produce_replay_summary(
            distinct_id="user",
            session_id=with_logs_session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            console_warn_count=4,
            log_messages={
                "warn": [
                    "warn",
                    "warn",
                    "warn",
                    "warn",
                ],
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=without_logs_session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "console_log_filters": '[{"key": "level", "value": ["warn"], "operator": "exact", "type": "log_entry"}]',
                "operand": "AND",
            }
        )

        assert sorted(
            [(sr["session_id"], sr["console_warn_count"]) for sr in session_recordings],
            key=lambda x: x[0],
        ) == [
            (with_logs_session_id, 4),
        ]

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "console_log_filters": '[{"key": "level", "value": ["info"], "operator": "exact", "type": "log_entry"}]',
                "operand": "AND",
            }
        )

        assert session_recordings == []

    @snapshot_clickhouse_queries
    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_filter_for_recordings_with_console_errors(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

        with_logs_session_id = f"with-logs-session-{str(uuid4())}"
        without_logs_session_id = f"no-logs-session-{str(uuid4())}"

        produce_replay_summary(
            distinct_id="user",
            session_id=with_logs_session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            console_error_count=4,
            log_messages={
                "error": [
                    "error",
                    "error",
                    "error",
                    "error",
                ],
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=without_logs_session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "console_log_filters": '[{"key": "level", "value": ["error"], "operator": "exact", "type": "log_entry"}]',
                "operand": "AND",
            }
        )

        assert sorted(
            [(sr["session_id"], sr["console_error_count"]) for sr in session_recordings],
            key=lambda x: x[0],
        ) == [
            (with_logs_session_id, 4),
        ]

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "console_log_filters": '[{"key": "level", "value": ["info"], "operator": "exact", "type": "log_entry"}]',
                "operand": "AND",
            }
        )

        assert session_recordings == []

    @snapshot_clickhouse_queries
    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_filter_for_recordings_with_mixed_console_counts(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

        with_logs_session_id = f"with-logs-session-{str(uuid4())}"
        with_warns_session_id = f"with-warns-session-{str(uuid4())}"
        with_errors_session_id = f"with-errors-session-{str(uuid4())}"
        with_two_session_id = f"with-two-session-{str(uuid4())}"

        produce_replay_summary(
            distinct_id="user",
            session_id=with_logs_session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            console_log_count=4,
            log_messages={
                "info": [
                    "info",
                    "info",
                    "info",
                    "info",
                ],
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=with_warns_session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            console_warn_count=4,
            log_messages={
                "warn": [
                    "warn",
                    "warn",
                    "warn",
                    "warn",
                ],
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=with_errors_session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            console_error_count=4,
            log_messages={
                "error": [
                    "error",
                    "error",
                    "error",
                    "error",
                ],
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=with_two_session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            console_error_count=4,
            console_log_count=3,
            log_messages={
                "error": [
                    "error",
                    "error",
                    "error",
                    "error",
                ],
                "info": [
                    "info",
                    "info",
                    "info",
                ],
            },
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "console_log_filters": '[{"key": "level", "value": ["warn", "error"], "operator": "exact", "type": "log_entry"}]',
                "operand": "AND",
            }
        )

        assert sorted([sr["session_id"] for sr in session_recordings]) == sorted(
            [
                with_errors_session_id,
                with_two_session_id,
                with_warns_session_id,
            ]
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "console_log_filters": '[{"key": "level", "value": ["info"], "operator": "exact", "type": "log_entry"}]',
                "operand": "AND",
            }
        )

        assert sorted([sr["session_id"] for sr in session_recordings]) == sorted(
            [
                with_two_session_id,
                with_logs_session_id,
            ]
        )

    @snapshot_clickhouse_queries
    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_filter_for_recordings_by_console_text(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

        with_logs_session_id = "with-logs-session"
        with_warns_session_id = "with-warns-session"
        with_errors_session_id = "with-errors-session"
        with_two_session_id = "with-two-session"

        produce_replay_summary(
            distinct_id="user",
            session_id=with_logs_session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            console_log_count=4,
            log_messages={
                "info": [
                    "log message 1",
                    "log message 2",
                    "log message 3",
                    "log message 4",
                ]
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=with_warns_session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            console_warn_count=5,
            log_messages={
                "warn": [
                    "warn message 1",
                    "warn message 2",
                    "warn message 3",
                    "warn message 4",
                    "warn message 5",
                ]
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=with_errors_session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            console_error_count=4,
            log_messages={
                "error": [
                    "error message 1",
                    "error message 2",
                    "error message 3",
                    "error message 4",
                ]
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=with_two_session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            console_error_count=4,
            console_log_count=3,
            log_messages={
                "error": [
                    "error message 1",
                    "error message 2",
                    "error message 3",
                    "error message 4",
                ],
                "info": ["log message 1", "log message 2", "log message 3"],
            },
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                # there are 5 warn and 4 error logs, message 4 matches in both
                "console_log_filters": '[{"key": "level", "value": ["warn", "error"], "operator": "exact", "type": "log_entry"}, {"key": "message", "value": "message 4", "operator": "exact", "type": "log_entry"}]',
                "operand": "OR",
            }
        )

        assert sorted([sr["session_id"] for sr in session_recordings]) == sorted(
            [
                with_errors_session_id,
                with_two_session_id,
                with_warns_session_id,
            ]
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                # there are 5 warn and 4 error logs, message 5 matches only matches in warn
                "console_log_filters": '[{"key": "level", "value": ["warn", "error"], "operator": "exact", "type": "log_entry"}, {"key": "message", "value": "message 5", "operator": "icontains", "type": "log_entry"}]',
                "operand": "AND",
            }
        )

        assert sorted([sr["session_id"] for sr in session_recordings]) == sorted(
            [
                with_warns_session_id,
            ]
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                # message 5 does not match log level "info"
                "console_log_filters": '[{"key": "level", "value": ["info"], "operator": "exact", "type": "log_entry"}, {"key": "message", "value": "message 5", "operator": "icontains", "type": "log_entry"}]',
                "operand": "AND",
            }
        )

        assert sorted([sr["session_id"] for sr in session_recordings]) == []

    @snapshot_clickhouse_queries
    def test_filter_for_recordings_by_snapshot_source(self):
        user = "test_duration_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id_one = "session one id"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            team_id=self.team.id,
            snapshot_source="web",
        )

        session_id_two = "session two id"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_two,
            team_id=self.team.id,
            snapshot_source="mobile",
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "having_predicates": '[{"key": "snapshot_source", "value": ["web"], "operator": "exact", "type": "recording"}]'
            }
        )
        assert [r["session_id"] for r in session_recordings] == [session_id_one]

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "having_predicates": '[{"key": "snapshot_source", "value": ["mobile"], "operator": "exact", "type": "recording"}]'
            }
        )
        assert [r["session_id"] for r in session_recordings] == [session_id_two]

    @also_test_with_materialized_columns(
        event_properties=["is_internal_user"],
        person_properties=["email"],
        verify_no_jsonextract=False,
    )
    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_event_filter_with_test_accounts_excluded(self):
        self.team.test_account_filters = [
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            },
            {
                "key": "is_internal_user",
                "value": ["false"],
                "operator": "exact",
                "type": "event",
            },
            {"key": "properties.$browser == 'Chrome'", "type": "hogql"},
        ]
        self.team.save()

        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        self.create_event(
            "user",
            self.an_hour_ago,
            properties={
                "$session_id": "1",
                "$window_id": "1",
                "is_internal_user": "true",
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "filter_test_accounts": True,
            }
        )
        self.assertEqual(len(session_recordings), 0)

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "filter_test_accounts": False,
            }
        )
        self.assertEqual(len(session_recordings), 1)

    @also_test_with_materialized_columns(
        event_properties=["$browser"],
        person_properties=["email"],
        verify_no_jsonextract=False,
    )
    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_event_filter_with_hogql_event_properties_test_accounts_excluded(self):
        self.team.test_account_filters = [
            {"key": "properties.$browser == 'Chrome'", "type": "hogql"},
        ]
        self.team.save()

        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        Person.objects.create(
            team=self.team,
            distinct_ids=["user2"],
            properties={"email": "not-the-other-one"},
        )

        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        self.create_event(
            "user",
            self.an_hour_ago,
            properties={"$session_id": "1", "$window_id": "1", "$browser": "Chrome"},
        )
        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        produce_replay_summary(
            distinct_id="user2",
            session_id="2",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        self.create_event(
            "user2",
            self.an_hour_ago,
            properties={"$session_id": "2", "$window_id": "1", "$browser": "Firefox"},
        )

        # there are 2 pageviews
        (session_recordings, _, _) = self._filter_recordings_by(
            {
                # pageview that matches the hogql test_accounts filter
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "filter_test_accounts": False,
            }
        )
        self.assertEqual(len(session_recordings), 2)

        self.team.test_account_filters = [
            {"key": "person.properties.email == 'bla'", "type": "hogql"},
        ]
        self.team.save()

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                # only 1 pageview that matches the hogql test_accounts filter
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "filter_test_accounts": True,
            }
        )
        self.assertEqual(len(session_recordings), 1)

        self.team.test_account_filters = [
            {"key": "properties.$browser == 'Chrome'", "type": "hogql"},
            {"key": "person.properties.email == 'bla'", "type": "hogql"},
        ]
        self.team.save()

        # one user sessions matches the person + event test_account filter
        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "filter_test_accounts": True,
            }
        )
        self.assertEqual(len(session_recordings), 1)

    # TRICKY: we had to disable use of materialized columns for part of the query generation
    # due to RAM usage issues on the EU cluster
    @also_test_with_materialized_columns(event_properties=["is_internal_user"], verify_no_jsonextract=False)
    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_top_level_event_property_test_account_filter(self):
        """
        This is a regression test. A user with an $ip test account filter
        reported the filtering wasn't working.

        The filter wasn't triggering the "should join events check", and so we didn't apply the filter at all
        """
        self.team.test_account_filters = [
            {
                "key": "is_internal_user",
                "value": ["false"],
                "operator": "exact",
                "type": "event",
            },
        ]
        self.team.save()

        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        Person.objects.create(
            team=self.team,
            distinct_ids=["user2"],
            properties={"email": "not-the-other-one"},
        )

        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        self.create_event(
            "user",
            self.an_hour_ago,
            properties={
                "$session_id": "1",
                "$window_id": "1",
                "is_internal_user": False,
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        produce_replay_summary(
            distinct_id="user2",
            session_id="2",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        self.create_event(
            "user2",
            self.an_hour_ago,
            properties={
                "$session_id": "2",
                "$window_id": "1",
                "is_internal_user": True,
            },
        )

        # there are 2 pageviews
        (session_recordings, _, _) = self._filter_recordings_by(
            {
                # pageview that matches the hogql test_accounts filter
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "filter_test_accounts": False,
            }
        )
        self.assertEqual(len(session_recordings), 2)

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                # only 1 pageview that matches the test_accounts filter
                "filter_test_accounts": True,
            }
        )
        self.assertEqual(len(session_recordings), 1)

    # TRICKY: we had to disable use of materialized columns for part of the query generation
    # due to RAM usage issues on the EU cluster
    @also_test_with_materialized_columns(event_properties=["is_internal_user"], verify_no_jsonextract=True)
    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_top_level_event_property_test_account_filter_allowing_denormalized_props(self):
        """
        This is a duplicate of the test test_top_level_event_property_test_account_filter
        but with denormalized props allowed
        """

        with self.settings(ALLOW_DENORMALIZED_PROPS_IN_LISTING=True):
            self.team.test_account_filters = [
                {
                    "key": "is_internal_user",
                    "value": ["false"],
                    "operator": "exact",
                    "type": "event",
                },
            ]
            self.team.save()

            Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
            Person.objects.create(
                team=self.team,
                distinct_ids=["user2"],
                properties={"email": "not-the-other-one"},
            )

            produce_replay_summary(
                distinct_id="user",
                session_id="1",
                first_timestamp=self.an_hour_ago,
                team_id=self.team.id,
            )
            self.create_event(
                "user",
                self.an_hour_ago,
                properties={
                    "$session_id": "1",
                    "$window_id": "1",
                    "is_internal_user": False,
                },
            )
            produce_replay_summary(
                distinct_id="user",
                session_id="1",
                first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
                team_id=self.team.id,
            )

            produce_replay_summary(
                distinct_id="user2",
                session_id="2",
                first_timestamp=self.an_hour_ago,
                team_id=self.team.id,
            )
            self.create_event(
                "user2",
                self.an_hour_ago,
                properties={
                    "$session_id": "2",
                    "$window_id": "1",
                    "is_internal_user": True,
                },
            )

            # there are 2 pageviews
            (session_recordings, _, _) = self._filter_recordings_by(
                {
                    # pageview that matches the hogql test_accounts filter
                    "events": [
                        {
                            "id": "$pageview",
                            "type": "events",
                            "order": 0,
                            "name": "$pageview",
                        }
                    ],
                    "filter_test_accounts": False,
                }
            )
            self.assertEqual(len(session_recordings), 2)

            (session_recordings, _, _) = self._filter_recordings_by(
                {
                    # only 1 pageview that matches the test_accounts filter
                    "filter_test_accounts": True,
                }
            )
            self.assertEqual(len(session_recordings), 1)

    @also_test_with_materialized_columns(event_properties=["is_internal_user"])
    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_top_level_hogql_event_property_test_account_filter(self):
        """
        This is a regression test. A user with an $ip test account filter
        reported the filtering wasn't working.

        The filter wasn't triggering the "should join events" check, and so we didn't apply the filter at all
        """
        self.team.test_account_filters = [
            {"key": "properties.is_internal_user == 'true'", "type": "hogql"},
        ]
        self.team.save()

        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        Person.objects.create(
            team=self.team,
            distinct_ids=["user2"],
            properties={"email": "not-the-other-one"},
        )

        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        self.create_event(
            "user",
            self.an_hour_ago,
            properties={
                "$session_id": "1",
                "$window_id": "1",
                "is_internal_user": False,
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        produce_replay_summary(
            distinct_id="user2",
            session_id="2",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        self.create_event(
            "user2",
            self.an_hour_ago,
            properties={
                "$session_id": "2",
                "$window_id": "1",
                "is_internal_user": True,
            },
        )

        # there are 2 pageviews
        (session_recordings, _, _) = self._filter_recordings_by(
            {
                # pageview that matches the hogql test_accounts filter
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "filter_test_accounts": False,
            }
        )
        self.assertEqual(len(session_recordings), 2)

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                # only 1 pageview that matches the test_accounts filter
                "filter_test_accounts": True,
            }
        )
        self.assertEqual(len(session_recordings), 1)

    @also_test_with_materialized_columns(person_properties=["email"], verify_no_jsonextract=False)
    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_top_level_hogql_person_property_test_account_filter(self):
        """
        This is a regression test. A user with an $ip test account filter
        reported the filtering wasn't working.

        The filter wasn't triggering the "should join events" check, and so we didn't apply the filter at all
        """
        self.team.test_account_filters = [
            {"key": "person.properties.email == 'bla'", "type": "hogql"},
        ]
        self.team.save()

        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        Person.objects.create(
            team=self.team,
            distinct_ids=["user2"],
            properties={"email": "not-the-other-one"},
        )

        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        self.create_event(
            "user",
            self.an_hour_ago,
            properties={
                "$session_id": "1",
                "$window_id": "1",
                "is_internal_user": False,
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        produce_replay_summary(
            distinct_id="user2",
            session_id="2",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        self.create_event(
            "user2",
            self.an_hour_ago,
            properties={
                "$session_id": "2",
                "$window_id": "1",
                "is_internal_user": True,
            },
        )

        # there are 2 pageviews
        (session_recordings, _, _) = self._filter_recordings_by(
            {
                # pageview that matches the hogql test_accounts filter
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "filter_test_accounts": False,
            }
        )
        self.assertEqual(len(session_recordings), 2)

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                # only 1 pageview that matches the test_accounts filter
                "filter_test_accounts": True,
            }
        )
        self.assertEqual(len(session_recordings), 1)

    @also_test_with_materialized_columns(person_properties=["email"], verify_no_jsonextract=False)
    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_top_level_person_property_test_account_filter(self):
        """
        This is a regression test. A user with an $ip test account filter
        reported the filtering wasn't working.

        The filter wasn't triggering the "should join events" check, and so we didn't apply the filter at all
        """
        self.team.test_account_filters = [{"key": "email", "value": ["bla"], "operator": "exact", "type": "person"}]
        self.team.save()

        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        Person.objects.create(
            team=self.team,
            distinct_ids=["user2"],
            properties={"email": "not-the-other-one"},
        )

        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        self.create_event(
            "user",
            self.an_hour_ago,
            properties={
                "$session_id": "1",
                "$window_id": "1",
                "is_internal_user": False,
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        produce_replay_summary(
            distinct_id="user2",
            session_id="2",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        self.create_event(
            "user2",
            self.an_hour_ago,
            properties={
                "$session_id": "2",
                "$window_id": "1",
                "is_internal_user": True,
            },
        )

        # there are 2 pageviews
        (session_recordings, _, _) = self._filter_recordings_by(
            {
                # pageview that matches the hogql test_accounts filter
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "filter_test_accounts": False,
            }
        )
        self.assertEqual(len(session_recordings), 2)

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                # only 1 pageview that matches the test_accounts filter
                "filter_test_accounts": True,
            }
        )
        self.assertEqual(len(session_recordings), 1)

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_event_filter_with_two_events_and_multiple_teams(self):
        another_team = Team.objects.create(organization=self.organization)

        # two teams, user with the same properties
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        Person.objects.create(team=another_team, distinct_ids=["user"], properties={"email": "bla"})

        # a recording session with a pageview and a pageleave
        self._a_session_with_two_events(self.team, "1")
        self._a_session_with_two_events(another_team, "2")

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    },
                    {
                        "id": "$pageleave",
                        "type": "events",
                        "order": 0,
                        "name": "$pageleave",
                    },
                ],
            }
        )

        self.assertEqual([sr["session_id"] for sr in session_recordings], ["1"])

    def _a_session_with_two_events(self, team: Team, session_id: str) -> None:
        produce_replay_summary(
            distinct_id="user",
            session_id=session_id,
            first_timestamp=self.an_hour_ago,
            team_id=team.pk,
        )
        self.create_event(
            "user",
            self.an_hour_ago,
            team=team,
            event_name="$pageview",
            properties={"$session_id": session_id, "$window_id": "1"},
        )
        self.create_event(
            "user",
            self.an_hour_ago,
            team=team,
            event_name="$pageleave",
            properties={"$session_id": session_id, "$window_id": "1"},
        )

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_event_filter_with_group_filter(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        session_id = f"test_event_filter_with_group_filter-ONE-{uuid4()}"
        different_group_session = f"test_event_filter_with_group_filter-TWO-{uuid4()}"

        produce_replay_summary(
            distinct_id="user",
            session_id=session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.pk,
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=different_group_session,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.pk,
        )

        GroupTypeMapping.objects.create(team=self.team, group_type="project", group_type_index=0)
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="project:1",
            properties={"name": "project one"},
        )

        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=1)
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="org:1",
            properties={"name": "org one"},
        )

        self.create_event(
            "user",
            self.an_hour_ago,
            team=self.team,
            event_name="$pageview",
            properties={
                "$session_id": session_id,
                "$window_id": "1",
                "$group_1": "org:1",
            },
        )
        self.create_event(
            "user",
            self.an_hour_ago,
            team=self.team,
            event_name="$pageview",
            properties={
                "$session_id": different_group_session,
                "$window_id": "1",
                "$group_0": "project:1",
            },
        )

        (session_recordings, _, _) = self._filter_recordings_by(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "properties": [
                            {
                                "key": "name",
                                "value": ["org one"],
                                "operator": "exact",
                                "type": "group",
                                "group_type_index": 1,
                            }
                        ],
                    }
                ],
            }
        )

        self.assertEqual([sr["session_id"] for sr in session_recordings], [session_id])
