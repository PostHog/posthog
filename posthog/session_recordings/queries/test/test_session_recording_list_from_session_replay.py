from datetime import datetime
from uuid import uuid4

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun.api import freeze_time

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.log_entries import TRUNCATE_LOG_ENTRIES_TABLE_SQL
from posthog.cloud_utils import TEST_clear_cloud_cache
from posthog.constants import AvailableFeature
from posthog.models import Person, Cohort, GroupTypeMapping
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.group.util import create_group
from posthog.session_recordings.sql.session_replay_event_sql import (
    TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL,
)
from posthog.models.team import Team
from posthog.session_recordings.queries.session_recording_list_from_replay_summary import (
    SessionRecordingListFromReplaySummary,
)
from posthog.session_recordings.queries.session_replay_events import ttl_days
from posthog.session_recordings.queries.test.session_replay_sql import (
    produce_replay_summary,
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
class TestClickhouseSessionRecordingsListFromSessionReplay(ClickhouseTestMixin, APIBaseTest):
    # this test does not create any session_recording_events, only writes to the session_replay summary table
    # it is a pair with test_session_recording_list
    # it should pass all the same tests but without needing the session_recording_events table at all

    @classmethod
    def teardown_class(cls):
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())
        sync_execute(TRUNCATE_LOG_ENTRIES_TABLE_SQL)

    def create_action(self, name, team_id=None, properties=None):
        if team_id is None:
            team_id = self.team.pk
        if properties is None:
            properties = []
        action = Action.objects.create(team_id=team_id, name=name)
        ActionStep.objects.create(action=action, event=name, properties=properties)
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

    @property
    def base_time(self):
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
            first_timestamp=self.base_time.isoformat().replace("T", " "),
            last_timestamp=(self.base_time + relativedelta(seconds=20)).isoformat().replace("T", " "),
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
            first_timestamp=(self.base_time + relativedelta(seconds=10)),
            last_timestamp=(self.base_time + relativedelta(seconds=50)),
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
            first_timestamp=(self.base_time + relativedelta(seconds=20)),
            last_timestamp=(self.base_time + relativedelta(seconds=2000)),
            distinct_id=user,
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=1980 * 1000 * 0.4,  # 40% of the total expected duration
        )

        filter = SessionRecordingsFilter(team=self.team, data={"no_filter": None})
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (
            session_recordings,
            more_recordings_available,
        ) = session_recording_list_instance.run()

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
                "start_time": self.base_time + relativedelta(seconds=20),
                "end_time": self.base_time + relativedelta(seconds=2000),
                "first_url": None,
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
                "start_time": self.base_time,
                "end_time": self.base_time + relativedelta(seconds=50),
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
            first_timestamp=self.base_time.isoformat().replace("T", " "),
            last_timestamp=(self.base_time + relativedelta(seconds=61)).isoformat().replace("T", " "),
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
            first_timestamp=(self.base_time),
            last_timestamp=(self.base_time + relativedelta(seconds=59)),
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
            first_timestamp=(self.base_time),
            last_timestamp=(self.base_time + relativedelta(seconds=61)),
            distinct_id=user,
            first_url="https://a-different-url.com",
            click_count=0,
            keypress_count=0,
            mouse_activity_count=0,
            active_milliseconds=0,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "duration_type_filter": "duration",
                "session_recording_duration": '{"type":"recording","key":"duration","value":60,"operator":"gt"}',
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (
            session_recordings,
            more_recordings_available,
        ) = session_recording_list_instance.run()

        assert sorted(
            [(s["session_id"], s["duration"], s["active_seconds"]) for s in session_recordings],
            key=lambda x: x[0],
        ) == [
            (session_id_inactive_is_61, 61, 0.0),
            (session_id_total_is_61, 61, 59.0),
        ]

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "duration_type_filter": "active_seconds",
                "session_recording_duration": '{"type":"recording","key":"duration","value":60,"operator":"gt"}',
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (
            session_recordings,
            more_recordings_available,
        ) = session_recording_list_instance.run()

        assert [(s["session_id"], s["duration"], s["active_seconds"]) for s in session_recordings] == [
            (session_id_active_is_61, 59, 61.0)
        ]

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "duration_type_filter": "inactive_seconds",
                "session_recording_duration": '{"type":"recording","key":"duration","value":60,"operator":"gt"}',
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (
            session_recordings,
            more_recordings_available,
        ) = session_recording_list_instance.run()

        assert [(s["session_id"], s["duration"], s["inactive_seconds"]) for s in session_recordings] == [
            (session_id_inactive_is_61, 61, 61.0)
        ]

    @snapshot_clickhouse_queries
    def test_basic_query_with_paging(self):
        user = "test_basic_query_with_paging-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id_one = f"test_basic_query_with_paging-{str(uuid4())}"
        session_id_two = f"test_basic_query_with_paging-{str(uuid4())}"

        produce_replay_summary(
            session_id=session_id_one,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp=self.base_time.isoformat().replace("T", " "),
            last_timestamp=(self.base_time + relativedelta(seconds=20)).isoformat().replace("T", " "),
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
            first_timestamp=(self.base_time + relativedelta(seconds=10)),
            last_timestamp=(self.base_time + relativedelta(seconds=50)),
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
            first_timestamp=(self.base_time + relativedelta(seconds=20)),
            last_timestamp=(self.base_time + relativedelta(seconds=2000)),
            distinct_id=user,
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=1980 * 1000 * 0.4,  # 40% of the total expected duration
        )

        filter = SessionRecordingsFilter(team=self.team, data={"no_filter": None, "limit": 1, "offset": 0})
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (
            session_recordings,
            more_recordings_available,
        ) = session_recording_list_instance.run()

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
                "start_time": self.base_time + relativedelta(seconds=20),
                "end_time": self.base_time + relativedelta(seconds=2000),
                "first_url": None,
                "console_log_count": 0,
                "console_warn_count": 0,
                "console_error_count": 0,
            }
        ]

        assert more_recordings_available is True

        filter = SessionRecordingsFilter(team=self.team, data={"no_filter": None, "limit": 1, "offset": 1})
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (
            session_recordings,
            more_recordings_available,
        ) = session_recording_list_instance.run()

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
                "start_time": self.base_time,
                "end_time": self.base_time + relativedelta(seconds=50),
                "first_url": "https://example.io/home",
                "console_log_count": 0,
                "console_warn_count": 0,
                "console_error_count": 0,
            },
        ]

        assert more_recordings_available is False

        filter = SessionRecordingsFilter(team=self.team, data={"no_filter": None, "limit": 1, "offset": 2})
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (
            session_recordings,
            more_recordings_available,
        ) = session_recording_list_instance.run()

        assert session_recordings == []

        assert more_recordings_available is False

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
            first_timestamp=self.base_time,
            last_timestamp=self.base_time + relativedelta(seconds=20),
            first_url="https://on-first-event.com",
        )

        produce_replay_summary(
            session_id=session_id_one,
            team_id=self.team.pk,
            first_timestamp=self.base_time + relativedelta(seconds=10),
            last_timestamp=self.base_time + relativedelta(seconds=20),
            first_url="https://on-second-event.com",
        )

        produce_replay_summary(
            session_id=session_id_one,
            team_id=self.team.pk,
            first_timestamp=self.base_time + relativedelta(seconds=20),
            last_timestamp=self.base_time + relativedelta(seconds=40),
            first_url="https://on-third-event.com",
        )

        # session two has no URL on the first event
        produce_replay_summary(
            session_id=session_id_two,
            team_id=self.team.pk,
            first_timestamp=(self.base_time + relativedelta(seconds=10)),
            last_timestamp=(self.base_time + relativedelta(seconds=50)),
            first_url=None,
        )

        produce_replay_summary(
            session_id=session_id_two,
            team_id=self.team.pk,
            first_timestamp=(self.base_time + relativedelta(seconds=20)),
            last_timestamp=(self.base_time + relativedelta(seconds=30)),
            first_url="https://first-is-on-second-event.com",
        )

        produce_replay_summary(
            session_id=session_id_two,
            team_id=self.team.pk,
            first_timestamp=(self.base_time + relativedelta(seconds=25)),
            last_timestamp=(self.base_time + relativedelta(seconds=30)),
            first_url="https://another-on-the-session.com",
        )

        # session three has no URLs
        produce_replay_summary(
            session_id=session_id_three,
            team_id=self.team.pk,
            first_timestamp=self.base_time,
            last_timestamp=self.base_time + relativedelta(seconds=50),
            distinct_id=user,
            first_url=None,
        )

        produce_replay_summary(
            session_id=session_id_three,
            team_id=self.team.pk,
            first_timestamp=(self.base_time + relativedelta(seconds=10)),
            last_timestamp=self.base_time + relativedelta(seconds=50),
            distinct_id=user,
            first_url=None,
        )

        produce_replay_summary(
            session_id=session_id_three,
            team_id=self.team.pk,
            first_timestamp=(self.base_time + relativedelta(seconds=20)),
            last_timestamp=self.base_time + relativedelta(seconds=60),
            distinct_id=user,
            first_url=None,
        )

        # session four events are received out of order
        produce_replay_summary(
            session_id=session_id_four,
            team_id=self.team.pk,
            first_timestamp=self.base_time + relativedelta(seconds=20),
            last_timestamp=self.base_time + relativedelta(seconds=25),
            first_url="https://on-first-received-event.com",
        )
        produce_replay_summary(
            session_id=session_id_four,
            team_id=self.team.pk,
            first_timestamp=self.base_time + relativedelta(seconds=10),
            last_timestamp=self.base_time + relativedelta(seconds=25),
            first_url="https://on-second-received-event-but-actually-first.com",
        )

        filter = SessionRecordingsFilter(team=self.team, data={"no_filter": None})
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (
            session_recordings,
            more_recordings_available,
        ) = session_recording_list_instance.run()

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
            # mypy unhappy about this lambda 🤷️
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
            first_timestamp=self.base_time,
            last_timestamp=self.base_time + relativedelta(seconds=20),
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=20 * 1000 * 0.5,  # 50% of the total expected duration
        )

        produce_replay_summary(
            session_id=session_id_two,
            team_id=self.team.pk,
            distinct_id=user,
            first_timestamp=self.base_time,
            last_timestamp=self.base_time + relativedelta(seconds=20),
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=20 * 1000 * 0.5,  # 50% of the total expected duration
        )

        filter = SessionRecordingsFilter(team=self.team, data={"no_filter": None})
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

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
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        self.create_event(
            user,
            self.base_time,
            properties={"$session_id": session_id_one, "$window_id": str(uuid4())},
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ]
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id_one

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "events": [
                    {
                        "id": "$autocapture",
                        "type": "events",
                        "order": 0,
                        "name": "$autocapture",
                    }
                ]
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
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
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        # but the page view event is outside TTL
        self.create_event(
            user,
            self.base_time
            - relativedelta(days=SessionRecordingListFromReplaySummary.SESSION_RECORDINGS_DEFAULT_LIMIT + 1),
            properties={"$session_id": session_id_one, "$window_id": str(uuid4())},
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ]
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        assert len(session_recordings) == 0

        filter = SessionRecordingsFilter(team=self.team, data={})
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        # without an event filter the recording is present, showing that the TTL was applied to the events table too
        # we want this to limit the amount of event data we query
        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id_one

    @snapshot_clickhouse_queries
    def test_ttl_days(self):
        assert ttl_days(self.team) == 21

        TEST_clear_cloud_cache()
        with self.is_cloud(True):
            # Far enough in the future from `days_since_blob_ingestion` but not paid
            with freeze_time("2023-09-01T12:00:01Z"):
                assert ttl_days(self.team) == 30

            self.team.organization.available_features = [AvailableFeature.RECORDINGS_PLAYLISTS]

            # Far enough in the future from `days_since_blob_ingestion` but paid
            with freeze_time("2023-12-01T12:00:01Z"):
                assert ttl_days(self.team) == 90

            # Not far enough in the future from `days_since_blob_ingestion`
            with freeze_time("2023-09-05T12:00:01Z"):
                assert ttl_days(self.team) == 35

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
            self.base_time,
            properties={
                "$session_id": session_id_total_is_61,
                "$window_id": str(uuid4()),
            },
        )
        produce_replay_summary(
            session_id=session_id_total_is_61,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp=self.base_time.isoformat().replace("T", " "),
            last_timestamp=(self.base_time + relativedelta(seconds=61)).isoformat().replace("T", " "),
            distinct_id=user,
            first_url="https://example.io/home",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=59000,
        )

        self.create_event(
            user,
            self.base_time,
            properties={
                "$session_id": session_id_active_is_61,
                "$window_id": str(uuid4()),
            },
        )
        produce_replay_summary(
            session_id=session_id_active_is_61,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp=self.base_time,
            last_timestamp=(self.base_time + relativedelta(seconds=59)),
            distinct_id=user,
            first_url="https://a-different-url.com",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=61000,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "duration_type_filter": "duration",
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "session_recording_duration": '{"type":"recording","key":"duration","value":60,"operator":"gt"}',
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (
            session_recordings,
            more_recordings_available,
        ) = session_recording_list_instance.run()

        assert [(s["session_id"], s["duration"], s["active_seconds"]) for s in session_recordings] == [
            (session_id_total_is_61, 61, 59.0)
        ]

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "duration_type_filter": "active_seconds",
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "session_recording_duration": '{"type":"recording","key":"duration","value":60,"operator":"gt"}',
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (
            session_recordings,
            more_recordings_available,
        ) = session_recording_list_instance.run()

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
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        self.create_event(
            user,
            self.base_time,
            properties={
                "$browser": "Chrome",
                "$session_id": session_id_one,
                "$window_id": str(uuid4()),
            },
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=(self.base_time + relativedelta(seconds=30)),
            team_id=self.team.id,
        )
        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id_one

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        assert session_recordings == []

    @snapshot_clickhouse_queries
    def test_multiple_event_filters(self):
        session_id = f"test_multiple_event_filters-{str(uuid4())}"
        user = "test_multiple_event_filters-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )

        self.create_event(
            user,
            self.base_time,
            properties={"$session_id": session_id, "$window_id": "1"},
        )
        self.create_event(
            user,
            self.base_time,
            properties={"$session_id": session_id, "$window_id": "1"},
            event_name="new-event",
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=(self.base_time + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
        )

        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
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
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        self.create_event(
            user,
            self.base_time,
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
            first_timestamp=(self.base_time + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "actions": [
                    {
                        "id": action_with_properties.id,
                        "type": "actions",
                        "order": 1,
                        "name": "custom-event",
                    }
                ]
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        assert session_recordings == []

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "actions": [
                    {
                        "id": action_without_properties.id,
                        "type": "actions",
                        "order": 1,
                        "name": "custom-event",
                    }
                ]
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id_one

        # Adding properties to an action
        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        assert session_recordings == []

        # Adding matching properties to an action
        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

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
            first_timestamp=self.base_time,
            last_timestamp=(self.base_time + relativedelta(seconds=60)),
            team_id=self.team.id,
        )
        self.create_event(
            user,
            self.base_time,
            properties={"$session_id": session_id, "$window_id": window_id},
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.base_time,
            last_timestamp=(self.base_time + relativedelta(seconds=30)),
            team_id=self.team.id,
        )
        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ]
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert session_recordings == [
            {
                "session_id": session_id,
                "distinct_id": user,
                "duration": 60,
                "start_time": self.base_time,
                "end_time": self.base_time + relativedelta(seconds=60),
                "active_seconds": 0.0,
                "click_count": 0,
                "first_url": None,
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
        another_team = Team.objects.create(organization=self.organization)

        user = "test_duration_filter-user"
        Person.objects.create(team=another_team, distinct_ids=[user], properties={"email": "bla"})

        session_id_one = "session one is 29 seconds long"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=self.base_time,
            last_timestamp=(self.base_time + relativedelta(seconds=29)),
            team_id=another_team.id,
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=(self.base_time + relativedelta(seconds=28)),
            last_timestamp=(self.base_time + relativedelta(seconds=29)),
            team_id=another_team.id,
        )

        session_id_two = "session two is 61 seconds long"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_two,
            first_timestamp=self.base_time,
            last_timestamp=(self.base_time + relativedelta(seconds=61)),
            team_id=another_team.id,
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_two,
            first_timestamp=self.base_time,
            last_timestamp=(self.base_time + relativedelta(seconds=61)),
            team_id=another_team.id,
        )
        filter = SessionRecordingsFilter(
            team=another_team,
            data={"session_recording_duration": '{"type":"recording","key":"duration","value":60,"operator":"gt"}'},
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=another_team)
        (session_recordings, _) = session_recording_list_instance.run()
        assert [r["session_id"] for r in session_recordings] == [session_id_two]

        filter = SessionRecordingsFilter(
            team=another_team,
            data={"session_recording_duration": '{"type":"recording","key":"duration","value":60,"operator":"lt"}'},
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=another_team)
        (session_recordings, _) = session_recording_list_instance.run()
        assert [r["session_id"] for r in session_recordings] == [session_id_one]

    @snapshot_clickhouse_queries
    def test_date_from_filter(self):
        user = "test_date_from_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        produce_replay_summary(
            distinct_id=user,
            session_id="three days before base time",
            first_timestamp=(self.base_time - relativedelta(days=3, seconds=100)),
            last_timestamp=(self.base_time - relativedelta(days=3)),
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=user,
            session_id="two days before base time",
            first_timestamp=(self.base_time - relativedelta(days=2, seconds=100)),
            last_timestamp=(self.base_time - relativedelta(days=2)),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(team=self.team, data={"date_from": self.base_time.strftime("%Y-%m-%d")})
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        assert session_recordings == []

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"date_from": (self.base_time - relativedelta(days=2)).strftime("%Y-%m-%d")},
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == "two days before base time"

    @snapshot_clickhouse_queries
    def test_date_from_filter_cannot_search_before_ttl(self):
        with freeze_time(self.base_time):
            user = "test_date_from_filter_cannot_search_before_ttl-user"
            Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

            produce_replay_summary(
                distinct_id=user,
                session_id="storage is past ttl",
                first_timestamp=(self.base_time - relativedelta(days=22)),
                # an illegally long session but it started 22 days ago
                last_timestamp=(self.base_time - relativedelta(days=3)),
                team_id=self.team.id,
            )
            produce_replay_summary(
                distinct_id=user,
                session_id="storage is not past ttl",
                first_timestamp=(self.base_time - relativedelta(days=19)),
                last_timestamp=(self.base_time - relativedelta(days=2)),
                team_id=self.team.id,
            )

            filter = SessionRecordingsFilter(
                team=self.team,
                data={"date_from": (self.base_time - relativedelta(days=20)).strftime("%Y-%m-%d")},
            )
            session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
            (session_recordings, _) = session_recording_list_instance.run()
            assert len(session_recordings) == 1
            assert session_recordings[0]["session_id"] == "storage is not past ttl"

            filter = SessionRecordingsFilter(
                team=self.team,
                data={"date_from": (self.base_time - relativedelta(days=21)).strftime("%Y-%m-%d")},
            )
            session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
            (session_recordings, _) = session_recording_list_instance.run()
            assert len(session_recordings) == 1
            assert session_recordings[0]["session_id"] == "storage is not past ttl"

            filter = SessionRecordingsFilter(
                team=self.team,
                data={"date_from": (self.base_time - relativedelta(days=22)).strftime("%Y-%m-%d")},
            )
            session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
            (session_recordings, _) = session_recording_list_instance.run()
            assert len(session_recordings) == 1
            assert session_recordings[0]["session_id"] == "storage is not past ttl"

    @snapshot_clickhouse_queries
    def test_date_to_filter(self):
        user = "test_date_to_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        produce_replay_summary(
            distinct_id=user,
            session_id="three days before base time",
            first_timestamp=(self.base_time - relativedelta(days=3, seconds=100)),
            last_timestamp=(self.base_time - relativedelta(days=3)),
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=user,
            session_id="two days before base time",
            first_timestamp=(self.base_time - relativedelta(days=2, seconds=100)),
            last_timestamp=(self.base_time - relativedelta(days=2)),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"date_to": (self.base_time - relativedelta(days=4)).strftime("%Y-%m-%d")},
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        assert session_recordings == []

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"date_to": (self.base_time - relativedelta(days=3)).strftime("%Y-%m-%d")},
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == "three days before base time"

    def test_recording_that_spans_time_bounds(self):
        user = "test_recording_that_spans_time_bounds-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        day_line = datetime(2021, 11, 5)
        produce_replay_summary(
            distinct_id=user,
            session_id="1",
            first_timestamp=(day_line - relativedelta(hours=3)),
            last_timestamp=(day_line + relativedelta(hours=3)),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "date_to": day_line.strftime("%Y-%m-%d"),
                "date_from": (day_line - relativedelta(days=10)).strftime("%Y-%m-%d"),
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == "1"
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

        filter = SessionRecordingsFilter(team=self.team, data={"person_uuid": str(p.uuid)})
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        assert sorted([r["session_id"] for r in session_recordings]) == sorted([session_id_two, session_id_one])

    @snapshot_clickhouse_queries
    def test_person_id_filter_with_distinct_id_optimization(self):
        """
        this test only really exists for the snapshot...
        but with the setting enabled outputs different SQL
        including an events table filter in the persons query
        """
        three_user_ids = [str(uuid4()) for _ in range(3)]
        session_id_one = f"test_person_id_filter-{str(uuid4())}"
        session_id_two = f"test_person_id_filter-{str(uuid4())}"
        p = Person.objects.create(
            team=self.team,
            distinct_ids=[three_user_ids[0], three_user_ids[1]],
            properties={"email": "bla"},
        )

        _create_event(
            event="$pageview",
            distinct_id=three_user_ids[0],
            team=self.team,
            # can't use $session_id as a keyword arg directly, but we can unpack it from a dict :shrug:
            **{"$session_id": "in reality this should need to match but we just check for presence"},
            timestamp=datetime.now() - relativedelta(days=1),
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

        with self.settings(REPLAY_LISTING_DISTINCT_IDS_FROM_EVENTS_OPTIMISATION_TEAM_IDS=[self.team.pk]):
            filter = SessionRecordingsFilter(team=self.team, data={"person_uuid": str(p.uuid)})
            session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
            (session_recordings, _) = session_recording_list_instance.run()
            # we've not set up the events realistically
            # which means we can check the filter is being applied
            # because not all the sessions are returned
            # because we've only created one event, and we're now filtering by events presence
            assert sorted([r["session_id"] for r in session_recordings]) == sorted([session_id_one])

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
            first_timestamp=(self.base_time - relativedelta(days=3)),
            team_id=self.team.id,
        )
        produce_replay_summary(
            # does not match because of user distinct id
            distinct_id=three_user_ids[2],
            session_id=target_session_id,
            first_timestamp=(self.base_time - relativedelta(days=3)),
            team_id=self.team.id,
        )
        self.create_event(
            three_user_ids[0],
            self.base_time - relativedelta(days=3),
            properties={"$session_id": target_session_id},
        )
        self.create_event(
            three_user_ids[0],
            self.base_time - relativedelta(days=3),
            event_name="custom-event",
            properties={"$browser": "Chrome", "$session_id": target_session_id},
        )
        produce_replay_summary(
            distinct_id=three_user_ids[1],
            session_id=target_session_id,
            first_timestamp=(self.base_time - relativedelta(days=3) + relativedelta(hours=6)),
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=three_user_ids[1],
            # does not match because of session id
            session_id=str(uuid4()),
            first_timestamp=(self.base_time - relativedelta(days=3) + relativedelta(hours=6)),
            team_id=self.team.id,
        )

        flush_persons_and_events()

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "person_uuid": str(p.uuid),
                "date_to": (self.base_time + relativedelta(days=3)).strftime("%Y-%m-%d"),
                "date_from": (self.base_time - relativedelta(days=10)).strftime("%Y-%m-%d"),
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
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

    def test_teams_dont_leak_event_filter(self):
        user = "test_teams_dont_leak_event_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        another_team = Team.objects.create(organization=self.organization)

        session_id = f"test_teams_dont_leak_event_filter-{str(uuid4())}"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        self.create_event(1, self.base_time + relativedelta(seconds=15), team=another_team)
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=(self.base_time + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ]
            },
        )

        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        assert session_recordings == []

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(person_properties=["email"])
    def test_event_filter_with_person_properties(self):
        user_one = "test_event_filter_with_person_properties-user"
        user_two = "test_event_filter_with_person_properties-user2"
        session_id_one = f"test_event_filter_with_person_properties-1-{str(uuid4())}"
        session_id_two = f"test_event_filter_with_person_properties-2-{str(uuid4())}"

        Person.objects.create(team=self.team, distinct_ids=[user_one], properties={"email": "bla"})
        Person.objects.create(team=self.team, distinct_ids=[user_two], properties={"email": "bla2"})

        produce_replay_summary(
            distinct_id=user_one,
            session_id=session_id_one,
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=user_one,
            session_id=session_id_one,
            first_timestamp=(self.base_time + relativedelta(seconds=30)),
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=user_two,
            session_id=session_id_two,
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=user_two,
            session_id=session_id_two,
            first_timestamp=(self.base_time + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "properties": [
                    {
                        "key": "email",
                        "value": ["bla"],
                        "operator": "exact",
                        "type": "person",
                    }
                ]
            },
        )

        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id_one

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
                    first_timestamp=self.base_time,
                    team_id=self.team.id,
                )
                # self.create_event(user_one, self.base_time, team=self.team)
                produce_replay_summary(
                    distinct_id=user_one,
                    session_id=session_id_one,
                    first_timestamp=self.base_time + relativedelta(seconds=30),
                    team_id=self.team.id,
                )
                produce_replay_summary(
                    distinct_id=user_two,
                    session_id=session_id_two,
                    first_timestamp=self.base_time,
                    team_id=self.team.id,
                )
                # self.create_event(user_two, self.base_time, team=self.team)
                produce_replay_summary(
                    distinct_id=user_two,
                    session_id=session_id_two,
                    first_timestamp=self.base_time + relativedelta(seconds=30),
                    team_id=self.team.id,
                )
                filter = SessionRecordingsFilter(
                    team=self.team,
                    data={
                        "properties": [
                            {
                                "key": "id",
                                "value": cohort.pk,
                                "operator": None,
                                "type": "cohort",
                            }
                        ]
                    },
                )
                session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
                (session_recordings, _) = session_recording_list_instance.run()

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
                    first_timestamp=self.base_time,
                    team_id=self.team.id,
                )
                self.create_event(
                    user_one,
                    self.base_time,
                    team=self.team,
                    event_name="custom_event",
                    properties={"$session_id": session_id_one},
                )
                produce_replay_summary(
                    distinct_id=user_one,
                    session_id=session_id_one,
                    first_timestamp=self.base_time + relativedelta(seconds=30),
                    team_id=self.team.id,
                )
                produce_replay_summary(
                    distinct_id=user_two,
                    session_id=session_id_two,
                    first_timestamp=self.base_time,
                    team_id=self.team.id,
                )
                self.create_event(
                    user_two,
                    self.base_time,
                    team=self.team,
                    event_name="custom_event",
                    properties={"$session_id": session_id_two},
                )
                produce_replay_summary(
                    distinct_id=user_two,
                    session_id=session_id_two,
                    first_timestamp=self.base_time + relativedelta(seconds=30),
                    team_id=self.team.id,
                )

                filter = SessionRecordingsFilter(
                    team=self.team,
                    data={
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
                    },
                )
                session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
                (session_recordings, _) = session_recording_list_instance.run()

                assert len(session_recordings) == 0

                filter = SessionRecordingsFilter(
                    team=self.team,
                    data={
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
                    },
                )
                session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
                (session_recordings, _) = session_recording_list_instance.run()

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
            self.base_time,
            event_name="$pageview",
            properties={"$session_id": session_id},
        )
        self.create_event(
            user_distinct_id,
            self.base_time,
            event_name="$autocapture",
            properties={"$session_id": str(uuid4())},
        )

        produce_replay_summary(
            distinct_id=user_distinct_id,
            session_id=session_id,
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=user_distinct_id,
            session_id=session_id,
            first_timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ]
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "events": [
                    {
                        "id": "$autocapture",
                        "type": "events",
                        "order": 0,
                        "name": "$autocapture",
                    }
                ]
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        assert session_recordings == []

    @also_test_with_materialized_columns(event_properties=["$current_url", "$browser"], person_properties=["email"])
    @snapshot_clickhouse_queries
    def test_event_filter_with_hogql_properties(self):
        user = "test_event_filter_with_hogql_properties-user"

        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id = f"test_event_filter_with_hogql_properties-1-{str(uuid4())}"
        self.create_event(
            user,
            self.base_time,
            properties={
                "$browser": "Chrome",
                "$session_id": session_id,
                "$window_id": str(uuid4()),
            },
        )

        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "properties": [{"key": "properties.$browser == 'Firefox'", "type": "hogql"}],
                    }
                ]
            },
        )

        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert session_recordings == []

    @snapshot_clickhouse_queries
    def test_event_filter_with_hogql_person_properties(self):
        user = "test_event_filter_with_hogql_properties-user"

        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id = f"test_event_filter_with_hogql_properties-1-{str(uuid4())}"
        self.create_event(
            user,
            self.base_time,
            properties={
                "$browser": "Chrome",
                "$session_id": session_id,
                "$window_id": str(uuid4()),
            },
        )

        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert len(session_recordings) == 1
        assert session_recordings[0]["session_id"] == session_id

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
            },
        )

        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

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
            self.base_time,
            properties={
                "$browser": "Chrome",
                "$session_id": page_view_session_id,
                "$window_id": "1",
            },
            event_name="$pageview",
        )

        self.create_event(
            "user",
            self.base_time,
            properties={
                "$browser": "Chrome",
                "$session_id": my_custom_event_session_id,
                "$window_id": "1",
            },
            event_name="my-custom-event",
        )

        self.create_event(
            "user",
            self.base_time,
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
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=my_custom_event_session_id,
            first_timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=non_matching__event_session_id,
            first_timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert sorted(
            [sr["session_id"] for sr in session_recordings],
            key=lambda x: x[0],
        ) == [
            my_custom_event_session_id,
            non_matching__event_session_id,
            page_view_session_id,
        ]

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert sorted(
            [sr["session_id"] for sr in session_recordings],
            key=lambda x: x[0],
        ) == [
            my_custom_event_session_id,
            page_view_session_id,
        ]

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
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
            first_timestamp=self.base_time,
            team_id=self.team.id,
            console_log_count=4,
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=without_logs_session_id,
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"console_logs": ["log"]},
        )

        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert sorted(
            [(sr["session_id"], sr["console_log_count"]) for sr in session_recordings],
            key=lambda x: x[0],
        ) == [
            (with_logs_session_id, 4),
        ]

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"console_logs": ["warn"]},
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
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
            first_timestamp=self.base_time,
            team_id=self.team.id,
            console_warn_count=4,
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=without_logs_session_id,
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"console_logs": ["warn"]},
        )

        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert sorted(
            [(sr["session_id"], sr["console_warn_count"]) for sr in session_recordings],
            key=lambda x: x[0],
        ) == [
            (with_logs_session_id, 4),
        ]

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"console_logs": ["log"]},
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
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
            first_timestamp=self.base_time,
            team_id=self.team.id,
            console_error_count=4,
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=without_logs_session_id,
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"console_logs": ["error"]},
        )

        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert sorted(
            [(sr["session_id"], sr["console_error_count"]) for sr in session_recordings],
            key=lambda x: x[0],
        ) == [
            (with_logs_session_id, 4),
        ]

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"console_logs": ["log"]},
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
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
            first_timestamp=self.base_time,
            team_id=self.team.id,
            console_log_count=4,
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=with_warns_session_id,
            first_timestamp=self.base_time,
            team_id=self.team.id,
            console_warn_count=4,
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=with_errors_session_id,
            first_timestamp=self.base_time,
            team_id=self.team.id,
            console_error_count=4,
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=with_two_session_id,
            first_timestamp=self.base_time,
            team_id=self.team.id,
            console_error_count=4,
            console_log_count=3,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"console_logs": ["warn", "error"]},
        )

        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert sorted([sr["session_id"] for sr in session_recordings]) == sorted(
            [
                with_errors_session_id,
                with_two_session_id,
                with_warns_session_id,
            ]
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"console_logs": ["log"]},
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
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
            first_timestamp=self.base_time,
            team_id=self.team.id,
            console_log_count=4,
            log_messages={
                "log": [
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
            first_timestamp=self.base_time,
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
            first_timestamp=self.base_time,
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
            first_timestamp=self.base_time,
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
                "log": ["log message 1", "log message 2", "log message 3"],
            },
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            # there are 5 warn and 4 error logs, message 4 matches in both
            data={
                "console_logs": ["warn", "error"],
                "console_search_query": "message 4",
            },
        )

        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert sorted([sr["session_id"] for sr in session_recordings]) == sorted(
            [
                with_errors_session_id,
                with_two_session_id,
                with_warns_session_id,
            ]
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            # there are 5 warn and 4 error logs, message 5 matches only matches in warn
            data={
                "console_logs": ["warn", "error"],
                "console_search_query": "message 5",
            },
        )

        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert sorted([sr["session_id"] for sr in session_recordings]) == sorted(
            [
                with_warns_session_id,
            ]
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            # match is case-insensitive
            data={
                "console_logs": ["warn", "error"],
                "console_search_query": "MESSAGE 5",
            },
        )

        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        assert sorted([sr["session_id"] for sr in session_recordings]) == sorted(
            [
                with_warns_session_id,
            ]
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            # message 5 does not match log level "log
            data={"console_logs": ["log"], "console_search_query": "message 5"},
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        assert sorted([sr["session_id"] for sr in session_recordings]) == sorted([])

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
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        self.create_event(
            "user",
            self.base_time,
            properties={
                "$session_id": "1",
                "$window_id": "1",
                "is_internal_user": "true",
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "filter_test_accounts": True,
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 0)

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "filter_test_accounts": False,
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
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
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        self.create_event(
            "user",
            self.base_time,
            properties={"$session_id": "1", "$window_id": "1", "$browser": "Chrome"},
        )
        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        produce_replay_summary(
            distinct_id="user2",
            session_id="2",
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        self.create_event(
            "user2",
            self.base_time,
            properties={"$session_id": "2", "$window_id": "1", "$browser": "Firefox"},
        )

        # there are 2 pageviews
        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 2)

        self.team.test_account_filters = [
            {"key": "person.properties.email == 'bla'", "type": "hogql"},
        ]
        self.team.save()

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)

        self.team.test_account_filters = [
            {"key": "properties.$browser == 'Chrome'", "type": "hogql"},
            {"key": "person.properties.email == 'bla'", "type": "hogql"},
        ]
        self.team.save()

        # one user sessions matches the person + event test_account filter
        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "filter_test_accounts": True,
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
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
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        self.create_event(
            "user",
            self.base_time,
            properties={
                "$session_id": "1",
                "$window_id": "1",
                "is_internal_user": False,
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        produce_replay_summary(
            distinct_id="user2",
            session_id="2",
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        self.create_event(
            "user2",
            self.base_time,
            properties={
                "$session_id": "2",
                "$window_id": "1",
                "is_internal_user": True,
            },
        )

        # there are 2 pageviews
        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 2)

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                # only 1 pageview that matches the test_accounts filter
                "filter_test_accounts": True,
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
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
                first_timestamp=self.base_time,
                team_id=self.team.id,
            )
            self.create_event(
                "user",
                self.base_time,
                properties={
                    "$session_id": "1",
                    "$window_id": "1",
                    "is_internal_user": False,
                },
            )
            produce_replay_summary(
                distinct_id="user",
                session_id="1",
                first_timestamp=self.base_time + relativedelta(seconds=30),
                team_id=self.team.id,
            )

            produce_replay_summary(
                distinct_id="user2",
                session_id="2",
                first_timestamp=self.base_time,
                team_id=self.team.id,
            )
            self.create_event(
                "user2",
                self.base_time,
                properties={
                    "$session_id": "2",
                    "$window_id": "1",
                    "is_internal_user": True,
                },
            )

            # there are 2 pageviews
            filter = SessionRecordingsFilter(
                team=self.team,
                data={
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
                },
            )
            session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
            (session_recordings, _) = session_recording_list_instance.run()
            self.assertEqual(len(session_recordings), 2)

            filter = SessionRecordingsFilter(
                team=self.team,
                data={
                    # only 1 pageview that matches the test_accounts filter
                    "filter_test_accounts": True,
                },
            )
            session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
            (session_recordings, _) = session_recording_list_instance.run()
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
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        self.create_event(
            "user",
            self.base_time,
            properties={
                "$session_id": "1",
                "$window_id": "1",
                "is_internal_user": False,
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        produce_replay_summary(
            distinct_id="user2",
            session_id="2",
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        self.create_event(
            "user2",
            self.base_time,
            properties={
                "$session_id": "2",
                "$window_id": "1",
                "is_internal_user": True,
            },
        )

        # there are 2 pageviews
        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 2)

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                # only 1 pageview that matches the test_accounts filter
                "filter_test_accounts": True,
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
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
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        self.create_event(
            "user",
            self.base_time,
            properties={
                "$session_id": "1",
                "$window_id": "1",
                "is_internal_user": False,
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        produce_replay_summary(
            distinct_id="user2",
            session_id="2",
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        self.create_event(
            "user2",
            self.base_time,
            properties={
                "$session_id": "2",
                "$window_id": "1",
                "is_internal_user": True,
            },
        )

        # there are 2 pageviews
        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 2)

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                # only 1 pageview that matches the test_accounts filter
                "filter_test_accounts": True,
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
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
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        self.create_event(
            "user",
            self.base_time,
            properties={
                "$session_id": "1",
                "$window_id": "1",
                "is_internal_user": False,
            },
        )
        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        produce_replay_summary(
            distinct_id="user2",
            session_id="2",
            first_timestamp=self.base_time,
            team_id=self.team.id,
        )
        self.create_event(
            "user2",
            self.base_time,
            properties={
                "$session_id": "2",
                "$window_id": "1",
                "is_internal_user": True,
            },
        )

        # there are 2 pageviews
        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 2)

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                # only 1 pageview that matches the test_accounts filter
                "filter_test_accounts": True,
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
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

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        self.assertEqual([sr["session_id"] for sr in session_recordings], ["1"])

    def _a_session_with_two_events(self, team: Team, session_id: str) -> None:
        produce_replay_summary(
            distinct_id="user",
            session_id=session_id,
            first_timestamp=self.base_time,
            team_id=team.pk,
        )
        self.create_event(
            "user",
            self.base_time,
            team=team,
            event_name="$pageview",
            properties={"$session_id": session_id, "$window_id": "1"},
        )
        self.create_event(
            "user",
            self.base_time,
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
            first_timestamp=self.base_time,
            team_id=self.team.pk,
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=different_group_session,
            first_timestamp=self.base_time,
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
            self.base_time,
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
            self.base_time,
            team=self.team,
            event_name="$pageview",
            properties={
                "$session_id": different_group_session,
                "$window_id": "1",
                "$group_0": "project:1",
            },
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
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
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        self.assertEqual([sr["session_id"] for sr in session_recordings], [session_id])
