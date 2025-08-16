from datetime import datetime
from uuid import uuid4

from dateutil.relativedelta import relativedelta
from freezegun import freeze_time

from posthog.models import Person
from posthog.session_recordings.queries.test.listing_recordings.base_test_session_recordings_list import (
    BaseTestSessionRecordingsList,
)
from posthog.session_recordings.queries.test.listing_recordings.test_utils import create_event
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.base import snapshot_clickhouse_queries


@freeze_time("2021-01-01T13:46:23")
class TestSessionRecordingListBasicQueries(BaseTestSessionRecordingsList):
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

        session_recordings, more_recordings_available, _ = self.filter_recordings_by()

        assert session_recordings == [
            {
                "session_id": session_id_two,
                "activity_score": 40.16,
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
                "ongoing": 1,
            },
            {
                "session_id": session_id_one,
                "activity_score": 61.11,
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
                "ongoing": 1,
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

        (session_recordings, _, _) = self.filter_recordings_by(
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

        (session_recordings, _, _) = self.filter_recordings_by(
            {
                "having_predicates": '[{"type":"recording","key":"active_seconds","value":"60","operator":"gt"}]',
            }
        )

        assert [(s["session_id"], s["duration"], s["active_seconds"]) for s in session_recordings] == [
            (session_id_active_is_61, 59, 61.0)
        ]

        (session_recordings, _, _) = self.filter_recordings_by(
            {
                "having_predicates": '[{"type":"recording","key":"inactive_seconds","value":"60","operator":"gt"}]',
            }
        )

        assert [(s["session_id"], s["duration"], s["inactive_seconds"]) for s in session_recordings] == [
            (session_id_inactive_is_61, 61, 61.0)
        ]

    @snapshot_clickhouse_queries
    def test_sessions_with_current_data(
        self,
    ):
        user = "test_sessions_with_current_data-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id_inactive = f"test_sessions_with_current_data-inactive-{str(uuid4())}"
        session_id_active = f"test_sessions_with_current_data-active-{str(uuid4())}"

        produce_replay_summary(
            session_id=session_id_inactive,
            team_id=self.team.pk,
            first_timestamp=self.an_hour_ago,
            last_timestamp=self.an_hour_ago + relativedelta(seconds=60),
            distinct_id=user,
            first_url="https://example.io/home",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=59000,
            kafka_timestamp=(datetime.utcnow() - relativedelta(minutes=6)),
        )

        produce_replay_summary(
            session_id=session_id_active,
            team_id=self.team.pk,
            first_timestamp=self.an_hour_ago,
            last_timestamp=self.an_hour_ago + relativedelta(seconds=60),
            distinct_id=user,
            first_url="https://a-different-url.com",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=61000,
            kafka_timestamp=(datetime.utcnow() - relativedelta(minutes=3)),
        )

        (session_recordings, _, _) = self.filter_recordings_by({})
        assert sorted(
            [(s["session_id"], s["ongoing"]) for s in session_recordings],
            key=lambda x: x[0],
        ) == [
            (session_id_active, 1),
            (session_id_inactive, 0),
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

        (session_recordings, more_recordings_available, _) = self.filter_recordings_by({"limit": 1, "offset": 0})

        assert session_recordings == [
            {
                "activity_score": 40.16,
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
                "ongoing": 1,
            }
        ]

        assert more_recordings_available is True

        (session_recordings, more_recordings_available, _) = self.filter_recordings_by({"limit": 1, "offset": 1})

        assert session_recordings == [
            {
                "session_id": session_id_one,
                "activity_score": 61.11,
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
                "ongoing": 1,
            },
        ]

        assert more_recordings_available is False

        self.assert_query_matches_session_ids({"limit": 1, "offset": 2}, [])

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

        (session_recordings) = self.filter_recordings_by({"limit": 3, "offset": 0, "order": "active_seconds"})

        ordered_by_activity = [(r["session_id"], r["active_seconds"]) for r in session_recordings.results]
        assert ordered_by_activity == [(session_id_two, 1.0), (session_id_one, 0.002)]

        (session_recordings) = self.filter_recordings_by({"limit": 3, "offset": 0, "order": "console_error_count"})

        ordered_by_errors = [(r["session_id"], r["console_error_count"]) for r in session_recordings.results]
        assert ordered_by_errors == [(session_id_one, 1012), (session_id_two, 430)]

        (session_recordings) = self.filter_recordings_by({"limit": 3, "offset": 0, "order": "start_time"})

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

        session_recordings, more_recordings_available, _ = self.filter_recordings_by()

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
            # mypy unhappy about this lambda when first_url can be None
            key=lambda x: x["session_id"],  # type: ignore
        )

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

        self.assert_query_matches_session_ids(
            {
                "session_ids": [first_session_id],
            },
            [first_session_id],
        )

        self.assert_query_matches_session_ids(
            {
                "session_ids": [first_session_id, second_session_id],
            },
            [
                first_session_id,
                second_session_id,
            ],
        )

    def test_all_sessions_recording_object_keys_with_entity_filter(self):
        user = "test_all_sessions_recording_object_keys_with_entity_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        session_id = f"test_all_sessions_recording_object_keys_with_entity_filter-{str(uuid4())}"
        window_id = str(uuid4())

        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.an_hour_ago + relativedelta(microsecond=1),
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=60)),
            team_id=self.team.id,
            first_url="https://recieved-out-of-order.com/second",
        )

        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago,
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

        (session_recordings, _, _) = self.filter_recordings_by(
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
                "activity_score": 0,
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
                "ongoing": 1,
            }
        ]

    def test_ordering(self):
        session_id_one = f"test_ordering-one"
        session_id_two = f"test_ordering-two"
        session_id_three = f"test_ordering-three"

        produce_replay_summary(
            session_id=session_id_one,
            team_id=self.team.id,
            mouse_activity_count=50,
            first_timestamp=(self.an_hour_ago + relativedelta(seconds=60)),
        )
        produce_replay_summary(
            session_id=session_id_two,
            team_id=self.team.id,
            mouse_activity_count=100,
            first_timestamp=self.an_hour_ago,
        )
        produce_replay_summary(
            session_id=session_id_three,
            team_id=self.team.id,
            mouse_activity_count=10,
            first_timestamp=(self.an_hour_ago + relativedelta(minutes=10)),
        )

        self.assert_query_matches_session_ids(
            {"order": "start_time"},
            [session_id_three, session_id_one, session_id_two],
            sort_results_when_asserting=False,
        )

        self.assert_query_matches_session_ids(
            {"order": "mouse_activity_count"},
            [session_id_two, session_id_one, session_id_three],
            sort_results_when_asserting=False,
        )
