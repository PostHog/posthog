from datetime import datetime
from typing import Literal
from uuid import uuid4

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_person,
    also_test_with_materialized_columns,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from unittest.mock import ANY

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from parameterized import parameterized, parameterized_class

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.log_entries import TRUNCATE_LOG_ENTRIES_TABLE_SQL
from posthog.constants import AvailableFeature
from posthog.models import Person
from posthog.models.action import Action
from posthog.models.cohort import Cohort
from posthog.models.group.util import create_group
from posthog.models.team import Team
from posthog.session_recordings.queries.session_recording_list_from_query import (
    SessionRecordingListFromQuery,
    SessionRecordingQueryResult,
)
from posthog.session_recordings.queries.session_replay_events import ttl_days
from posthog.session_recordings.queries.test.listing_recordings.test_utils import (
    assert_query_matches_session_ids,
    create_event,
    filter_recordings_by,
)
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from ee.clickhouse.models.test.test_cohort import get_person_ids_by_cohort_id


@parameterized_class([{"allow_event_property_expansion": True}, {"allow_event_property_expansion": False}])
@freeze_time("2021-01-01T13:46:23")
class TestSessionRecordingsListFromQuery(ClickhouseTestMixin, APIBaseTest):
    # set by parameterized_class decorator
    allow_event_property_expansion: bool

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

    # wrap the util so we don't have to pass the team every time
    def _filter_recordings_by(self, recordings_filter: dict | None = None) -> SessionRecordingQueryResult:
        return filter_recordings_by(
            team=self.team,
            recordings_filter=recordings_filter,
            allow_event_property_expansion=self.allow_event_property_expansion,
        )

    # wrap the util so we don't have to pass team every time
    def _assert_query_matches_session_ids(
        self, query: dict | None, expected: list[str], sort_results_when_asserting: bool = True
    ) -> None:
        assert_query_matches_session_ids(
            team=self.team, query=query, expected=expected, sort_results_when_asserting=sort_results_when_asserting
        )

    def _a_session_with_two_events(self, team: Team, session_id: str) -> None:
        produce_replay_summary(
            distinct_id="user",
            session_id=session_id,
            first_timestamp=self.an_hour_ago,
            team_id=team.pk,
        )
        create_event(
            distinct_id="user",
            timestamp=self.an_hour_ago,
            team=team,
            event_name="$pageview",
            properties={"$session_id": session_id, "$window_id": "1"},
        )
        create_event(
            distinct_id="user",
            timestamp=self.an_hour_ago,
            team=team,
            event_name="$pageleave",
            properties={"$session_id": session_id, "$window_id": "1"},
        )

    @property
    def an_hour_ago(self):
        return (now() - relativedelta(hours=1)).replace(microsecond=0, second=0)

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

        session_recordings, more_recordings_available, _ = self._filter_recordings_by()

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

        (session_recordings, _, _) = self._filter_recordings_by({})
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

        (session_recordings, more_recordings_available, _) = self._filter_recordings_by({"limit": 1, "offset": 0})

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

        (session_recordings, more_recordings_available, _) = self._filter_recordings_by({"limit": 1, "offset": 1})

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

        self._assert_query_matches_session_ids({"limit": 1, "offset": 2}, [])

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

        (session_recordings) = self._filter_recordings_by({"limit": 3, "offset": 0, "order": "active_seconds"})

        ordered_by_activity = [(r["session_id"], r["active_seconds"]) for r in session_recordings.results]
        assert ordered_by_activity == [(session_id_two, 1.0), (session_id_one, 0.002)]

        (session_recordings) = self._filter_recordings_by({"limit": 3, "offset": 0, "order": "console_error_count"})

        ordered_by_errors = [(r["session_id"], r["console_error_count"]) for r in session_recordings.results]
        assert ordered_by_errors == [(session_id_one, 1012), (session_id_two, 430)]

        (session_recordings) = self._filter_recordings_by({"limit": 3, "offset": 0, "order": "start_time"})

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

        session_recordings, more_recordings_available, _ = self._filter_recordings_by()

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

        (session_recordings, _, _) = self._filter_recordings_by()

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

        self._assert_query_matches_session_ids(
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

        self._assert_query_matches_session_ids(
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

        self._assert_query_matches_session_ids(
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
        self._assert_query_matches_session_ids({}, [session_id_one])

    @snapshot_clickhouse_queries
    def test_ttl_days(self):
        # hooby is 21 days
        assert ttl_days(self.team) == 21

        with self.is_cloud(True):
            # free users are 30 days
            with freeze_time("2023-09-01T12:00:01Z"):
                assert ttl_days(self.team) == 30

            self.team.organization.available_product_features = [
                {"key": AvailableFeature.RECORDINGS_FILE_EXPORT, "name": AvailableFeature.RECORDINGS_FILE_EXPORT}
            ]

            # paid is 90 days
            with freeze_time("2023-12-01T12:00:01Z"):
                assert ttl_days(self.team) == 90

    @snapshot_clickhouse_queries
    def test_listing_ignores_future_replays(self):
        with freeze_time("2023-08-29T12:00:01Z"):
            produce_replay_summary(team_id=self.team.id, session_id="29th Aug")

        with freeze_time("2023-08-30T14:00:01Z"):
            produce_replay_summary(team_id=self.team.id, session_id="30th Aug 1400")

        with freeze_time("2023-09-01T12:00:01Z"):
            produce_replay_summary(team_id=self.team.id, session_id="1st-sep")

        with freeze_time("2023-09-02T12:00:01Z"):
            produce_replay_summary(team_id=self.team.id, session_id="2nd-sep")

        with freeze_time("2023-09-03T12:00:01Z"):
            produce_replay_summary(team_id=self.team.id, session_id="3rd-sep")

        # before the recording on the thirtieth so should exclude it
        with freeze_time("2023-08-30T12:00:01Z"):
            # recordings in the future don't show
            self._assert_query_matches_session_ids(None, ["29th Aug"])

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

        self._assert_query_matches_session_ids(
            {
                "session_ids": [first_session_id],
            },
            [first_session_id],
        )

        self._assert_query_matches_session_ids(
            {
                "session_ids": [first_session_id, second_session_id],
            },
            [
                first_session_id,
                second_session_id,
            ],
        )

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

        self._assert_query_matches_session_ids(
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

        self._assert_query_matches_session_ids(
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

        self._assert_query_matches_session_ids(
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

        self._assert_query_matches_session_ids(
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

        self._assert_query_matches_session_ids(
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

        self._assert_query_matches_session_ids(
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
        self._assert_query_matches_session_ids(
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
        self._assert_query_matches_session_ids(
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
        self._assert_query_matches_session_ids(
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
        self._assert_query_matches_session_ids(
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

        self._assert_query_matches_session_ids(
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

        self._assert_query_matches_session_ids(
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
        self._assert_query_matches_session_ids(
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
        self._assert_query_matches_session_ids(
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

        self._assert_query_matches_session_ids(
            {"having_predicates": '[{"type":"recording","key":"duration","value":60,"operator":"gt"}]'},
            [session_id_two],
        )

        self._assert_query_matches_session_ids(
            {"having_predicates": '[{"type":"recording","key":"duration","value":60,"operator":"lt"}]'},
            [session_id_one],
        )

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

        self._assert_query_matches_session_ids(
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
            },
            [],
        )

        self._assert_query_matches_session_ids(
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
            },
            [session_id_one, session_id_two],
        )

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
        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago + relativedelta(seconds=10),
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
        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago + relativedelta(seconds=10),
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

        self._assert_query_matches_session_ids(
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
            },
            [],
        )

        self._assert_query_matches_session_ids(
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
            },
            [session_id_two, session_id_one],
        )

    @parameterized.expand(
        [
            # Case 1: Neither has WARN and message "random"
            (
                '[{"key": "level", "value": ["warn"], "operator": "exact", "type": "log_entry"}, {"key": "message", "value": "random", "operator": "exact", "type": "log_entry"}]',
                "AND",
                0,
                [],
            ),
            # Case 2: AND only matches one recording
            (
                '[{"key": "level", "value": ["info"], "operator": "exact", "type": "log_entry"}, {"key": "message", "value": "random", "operator": "exact", "type": "log_entry"}]',
                "AND",
                1,
                ["both_log_filters"],
            ),
            # Case 3: Only one is WARN level
            (
                '[{"key": "level", "value": ["warn"], "operator": "exact", "type": "log_entry"}]',
                "AND",
                1,
                ["one_log_filter"],
            ),
            # Case 4: Only one has message "random"
            (
                '[{"key": "message", "value": "random", "operator": "exact", "type": "log_entry"}]',
                "AND",
                1,
                ["both_log_filters"],
            ),
            # Case 5: OR matches both
            (
                '[{"key": "level", "value": ["warn"], "operator": "exact", "type": "log_entry"}, {"key": "message", "value": "random", "operator": "exact", "type": "log_entry"}]',
                "OR",
                2,
                ["both_log_filters", "one_log_filter"],
            ),
        ]
    )
    @snapshot_clickhouse_queries
    def test_operand_or_filters(
        self,
        console_log_filters: str,
        operand: Literal["AND", "OR"],
        expected_count: int,
        expected_session_ids: list[str],
    ) -> None:
        user = "test_operand_or_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_with_both_log_filters = "both_log_filters"
        produce_replay_summary(
            distinct_id="user",
            session_id=session_with_both_log_filters,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            console_log_count=1,
            log_messages={"info": ["random"]},
        )

        session_with_one_log_filter = "one_log_filter"
        produce_replay_summary(
            distinct_id="user",
            session_id=session_with_one_log_filter,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            console_warn_count=1,
            log_messages={"warn": ["warn"]},
        )

        self._assert_query_matches_session_ids(
            {"console_log_filters": console_log_filters, "operand": operand}, expected_session_ids
        )

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
        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago + relativedelta(seconds=10),
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
        self._assert_query_matches_session_ids(
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
            },
            [session_id_one],
        )

        # person or event filter -> person does not match, event matches -> does not return session
        self._assert_query_matches_session_ids(
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
            },
            [],
        )

        # session_id or event filter -> person matches, event matches -> returns session
        self._assert_query_matches_session_ids(
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
            },
            [session_id_one],
        )

        # session_id or event filter -> person does not match, event matches -> does not return session
        self._assert_query_matches_session_ids(
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
            },
            [],
        )

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

        self._assert_query_matches_session_ids({"date_from": self.an_hour_ago.strftime("%Y-%m-%d")}, [])

        self._assert_query_matches_session_ids(
            {"date_from": (self.an_hour_ago - relativedelta(days=2)).strftime("%Y-%m-%d")},
            ["two days before base time"],
        )

    @parameterized.expand(
        [
            (
                "that searching from 20 days ago excludes sessions past TTL",
                20,
            ),
            (
                "that searching from 21 days ago still excludes sessions past TTL",
                21,
            ),
            (
                "that even searching from 22 days ago (exactly at TTL boundary) excludes sessions past TTL",
                22,
            ),
        ]
    )
    @snapshot_clickhouse_queries
    def test_date_from_filter_respects_ttl(self, _name: str, days_ago: int):
        with freeze_time(self.an_hour_ago):
            user = "test_date_from_filter_cannot_search_before_ttl-user"
            Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

            # Create a session past TTL (22 days old)
            produce_replay_summary(
                distinct_id=user,
                session_id="storage is past ttl",
                first_timestamp=(self.an_hour_ago - relativedelta(days=22)),
                # an illegally long session but it started 22 days ago
                last_timestamp=(self.an_hour_ago - relativedelta(days=3)),
                team_id=self.team.id,
            )

            # Create a session within TTL (19 days old)
            produce_replay_summary(
                distinct_id=user,
                session_id="storage is not past ttl",
                first_timestamp=(self.an_hour_ago - relativedelta(days=19)),
                last_timestamp=(self.an_hour_ago - relativedelta(days=2)),
                team_id=self.team.id,
            )

            self._assert_query_matches_session_ids(
                {"date_from": (self.an_hour_ago - relativedelta(days=days_ago)).strftime("%Y-%m-%d")},
                ["storage is not past ttl"],
            )

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

        self._assert_query_matches_session_ids(
            {"date_to": (self.an_hour_ago - relativedelta(days=4)).strftime("%Y-%m-%d")}, []
        )

        self._assert_query_matches_session_ids(
            {"date_to": (self.an_hour_ago - relativedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")},
            ["three days before base time"],
        )

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

        assert [{"session_id": session_id, "duration": 6 * 60 * 60}] == [
            {"session_id": sr["session_id"], "duration": sr["duration"]} for sr in session_recordings
        ]

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

        self._assert_query_matches_session_ids({"person_uuid": str(p.uuid)}, [session_id_two, session_id_one])

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
        create_event(
            team=self.team,
            distinct_id=three_user_ids[0],
            timestamp=self.an_hour_ago - relativedelta(days=3),
            properties={"$session_id": target_session_id},
        )
        create_event(
            team=self.team,
            distinct_id=three_user_ids[0],
            timestamp=self.an_hour_ago - relativedelta(days=3),
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

        self._assert_query_matches_session_ids(
            {
                "person_uuid": str(p.uuid),
                "date_to": (self.an_hour_ago + relativedelta(days=3)).strftime("%Y-%m-%d"),
                "date_from": (self.an_hour_ago - relativedelta(days=10)).strftime("%Y-%m-%d"),
                "having_predicates": '[{"type":"recording","key":"duration","value":60,"operator":"gt"}]',
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
            [target_session_id],
        )

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
        create_event(distinct_id=user, timestamp=self.an_hour_ago + relativedelta(seconds=15), team=another_team)
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        self._assert_query_matches_session_ids(
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

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(person_properties=["email"])
    def test_filter_with_person_properties_exact(self):
        session_id_one, session_id_two = self._two_sessions_two_persons(
            "test_filter_with_person_properties_exact",
            session_one_person_properties={"email": "bla@gmail.com"},
            session_two_person_properties={"email": "bla2@hotmail.com"},
        )

        self._assert_query_matches_session_ids(
            {
                "properties": [
                    {
                        "key": "email",
                        "value": ["bla@gmail.com"],
                        "operator": "exact",
                        "type": "person",
                    }
                ]
            },
            [session_id_one],
        )

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(person_properties=["email"])
    def test_filter_with_person_properties_not_contains(self):
        session_id_one, session_id_two = self._two_sessions_two_persons(
            "test_filter_with_person_properties_not_contains",
            session_one_person_properties={"email": "bla@gmail.com"},
            session_two_person_properties={"email": "bla2@hotmail.com"},
        )

        self._assert_query_matches_session_ids(
            {"properties": [{"key": "email", "value": "gmail.com", "operator": "not_icontains", "type": "person"}]},
            [session_id_two],
        )

    @snapshot_clickhouse_queries
    @also_test_with_materialized_columns(["$current_url"])
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

        self._assert_query_matches_session_ids(
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

        self._assert_query_matches_session_ids(
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
    def test_event_filter_with_hogql_properties(self):
        user = "test_event_filter_with_hogql_properties-user"

        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id = f"test_event_filter_with_hogql_properties-1-{str(uuid4())}"
        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago,
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

        self._assert_query_matches_session_ids(
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
            },
            [session_id],
        )

        self._assert_query_matches_session_ids(
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
            },
            [],
        )

    @snapshot_clickhouse_queries
    def test_event_filter_with_hogql_person_properties(self):
        user = "test_event_filter_with_hogql_properties-user"

        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id = f"test_event_filter_with_hogql_properties-1-{str(uuid4())}"
        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago,
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

        self._assert_query_matches_session_ids(
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
            },
            [session_id],
        )

        self._assert_query_matches_session_ids(
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
            },
            [],
        )

    @also_test_with_materialized_columns(["$current_url", "$browser"])
    @snapshot_clickhouse_queries
    @freeze_time("2021-01-21T20:00:00.000Z")
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

        self._assert_query_matches_session_ids(
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

        self._assert_query_matches_session_ids(
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

        self._assert_query_matches_session_ids(
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

        self._assert_query_matches_session_ids(
            {
                "console_log_filters": '[{"key": "level", "value": ["warn"], "operator": "exact", "type": "log_entry"}]',
                "operand": "AND",
            },
            [],
        )

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

        self._assert_query_matches_session_ids(
            {
                "console_log_filters": '[{"key": "level", "value": ["info"], "operator": "exact", "type": "log_entry"}]',
                "operand": "AND",
            },
            [],
        )

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

        self._assert_query_matches_session_ids(
            {
                "console_log_filters": '[{"key": "level", "value": ["info"], "operator": "exact", "type": "log_entry"}]',
                "operand": "AND",
            },
            [],
        )

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

        self._assert_query_matches_session_ids(
            {
                "console_log_filters": '[{"key": "level", "value": ["warn", "error"], "operator": "exact", "type": "log_entry"}]',
                "operand": "AND",
            },
            [
                with_errors_session_id,
                with_two_session_id,
                with_warns_session_id,
            ],
        )

        self._assert_query_matches_session_ids(
            {
                "console_log_filters": '[{"key": "level", "value": ["info"], "operator": "exact", "type": "log_entry"}]',
                "operand": "AND",
            },
            [
                with_two_session_id,
                with_logs_session_id,
            ],
        )

    @parameterized.expand(
        [
            # Case 1: OR operand, message 4 matches in warn and error
            (
                '[{"key": "level", "value": ["warn", "error"], "operator": "exact", "type": "log_entry"}, {"key": "message", "value": "message 4", "operator": "icontains", "type": "log_entry"}]',
                "OR",
                ["with-errors-session", "with-two-session", "with-warns-session", "with-logs-session"],
            ),
            # Case 2: AND operand, message 4 matches in log, warn, and error
            (
                '[{"key": "level", "value": ["warn", "error"], "operator": "exact", "type": "log_entry"}, {"key": "message", "value": "message 4", "operator": "icontains", "type": "log_entry"}]',
                "AND",
                ["with-errors-session", "with-two-session", "with-warns-session"],
            ),
            # Case 2: AND operand, message 5 matches only in warn
            (
                '[{"key": "level", "value": ["warn", "error"], "operator": "exact", "type": "log_entry"}, {"key": "message", "value": "message 5", "operator": "icontains", "type": "log_entry"}]',
                "AND",
                ["with-warns-session"],
            ),
            # Case 3: AND operand, message 5 does not match log level "info"
            (
                '[{"key": "level", "value": ["info"], "operator": "exact", "type": "log_entry"}, {"key": "message", "value": "message 5", "operator": "icontains", "type": "log_entry"}]',
                "AND",
                [],
            ),
        ]
    )
    @snapshot_clickhouse_queries
    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_filter_for_recordings_by_console_text(
        self,
        console_log_filters: str,
        operand: Literal["AND", "OR"],
        expected_session_ids: list[str],
    ) -> None:
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

        # Create sessions
        produce_replay_summary(
            distinct_id="user",
            session_id="with-logs-session",
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
            session_id="with-warns-session",
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
            session_id="with-errors-session",
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
            session_id="with-two-session",
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
        produce_replay_summary(
            distinct_id="user",
            session_id="with-no-matches-session",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            console_error_count=4,
            console_log_count=3,
            log_messages={
                "info": ["log message 1", "log message 2", "log message 3"],
            },
        )

        self._assert_query_matches_session_ids(
            {"console_log_filters": console_log_filters, "operand": operand}, expected_session_ids
        )

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

        self._assert_query_matches_session_ids(
            {
                "having_predicates": '[{"key": "snapshot_source", "value": ["web"], "operator": "exact", "type": "recording"}]'
            },
            [session_id_one],
        )

        self._assert_query_matches_session_ids(
            {
                "having_predicates": '[{"key": "snapshot_source", "value": ["mobile"], "operator": "exact", "type": "recording"}]'
            },
            [session_id_two],
        )

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
                # in production some test account filters don't include type
                # we default to event in that case
                # "type": "event",
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
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
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

        self._assert_query_matches_session_ids(
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
            },
            [],
        )

        self._assert_query_matches_session_ids(
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
            },
            ["1"],
        )

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
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
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
        create_event(
            team=self.team,
            distinct_id="user2",
            timestamp=self.an_hour_ago,
            properties={"$session_id": "2", "$window_id": "1", "$browser": "Firefox"},
        )

        self._assert_query_matches_session_ids(
            {
                # there are 2 pageviews
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
            ["1", "2"],
        )

        self.team.test_account_filters = [
            {"key": "person.properties.email == 'bla'", "type": "hogql"},
        ]
        self.team.save()

        self._assert_query_matches_session_ids(
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
            },
            ["1"],
        )

        self.team.test_account_filters = [
            {"key": "properties.$browser == 'Chrome'", "type": "hogql"},
            {"key": "person.properties.email == 'bla'", "type": "hogql"},
        ]
        self.team.save()

        # one user sessions matches the person + event test_account filter
        self._assert_query_matches_session_ids(
            {
                "filter_test_accounts": True,
            },
            ["1"],
        )

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
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
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
        create_event(
            team=self.team,
            distinct_id="user2",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "2",
                "$window_id": "1",
                "is_internal_user": True,
            },
        )

        self._assert_query_matches_session_ids(
            {
                # there are 2 pageviews
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
            ["1", "2"],
        )

        self._assert_query_matches_session_ids(
            {
                # only 1 pageview that matches the test_accounts filter
                "filter_test_accounts": True,
            },
            ["1"],
        )

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
            create_event(
                team=self.team,
                distinct_id="user",
                timestamp=self.an_hour_ago,
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
            create_event(
                team=self.team,
                distinct_id="user2",
                timestamp=self.an_hour_ago,
                properties={
                    "$session_id": "2",
                    "$window_id": "1",
                    "is_internal_user": True,
                },
            )

            self._assert_query_matches_session_ids(
                {
                    # there are 2 pageviews
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
                ["1", "2"],
            )

            self._assert_query_matches_session_ids(
                {
                    # only 1 pageview that matches the test_accounts filter
                    "filter_test_accounts": True,
                },
                ["1"],
            )

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
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
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
        create_event(
            team=self.team,
            distinct_id="user2",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "2",
                "$window_id": "1",
                "is_internal_user": True,
            },
        )

        self._assert_query_matches_session_ids(
            {
                # there are 2 pageviews
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
            ["1", "2"],
        )

        self._assert_query_matches_session_ids(
            {
                # only 1 pageview that matches the test_accounts filter
                "filter_test_accounts": True,
            },
            ["2"],
        )

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
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
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
        create_event(
            team=self.team,
            distinct_id="user2",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "2",
                "$window_id": "1",
                "is_internal_user": True,
            },
        )

        self._assert_query_matches_session_ids(
            {
                # there are 2 pageviews
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
            ["1", "2"],
        )

        self._assert_query_matches_session_ids(
            {
                # only 1 pageview that matches the test_accounts filter
                "filter_test_accounts": True,
            },
            ["1"],
        )

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
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "event": "something that won't match",
                "$session_id": "1",
                "$window_id": "1",
                "is_internal_user": False,
            },
        )

        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
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
        create_event(
            team=self.team,
            distinct_id="user2",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "2",
                "$window_id": "1",
                "is_internal_user": True,
            },
        )

        # there are 2 pageviews
        self._assert_query_matches_session_ids(
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
            },
            ["1", "2"],
        )

        self._assert_query_matches_session_ids(
            {
                # only 1 pageview that matches the test_accounts filter
                "filter_test_accounts": True,
            },
            ["1"],
        )

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

        self._assert_query_matches_session_ids(
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
            },
            ["1"],
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

        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="project", group_type_index=0
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="project:1",
            properties={"name": "project one"},
        )

        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=1
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="org:1",
            properties={"name": "org one"},
        )

        create_event(
            distinct_id="user",
            timestamp=self.an_hour_ago,
            team=self.team,
            event_name="$pageview",
            properties={
                "$session_id": session_id,
                "$window_id": "1",
                "$group_1": "org:1",
            },
        )
        create_event(
            distinct_id="user",
            timestamp=self.an_hour_ago,
            team=self.team,
            event_name="$pageview",
            properties={
                "$session_id": different_group_session,
                "$window_id": "1",
                "$group_0": "project:1",
            },
        )

        self._assert_query_matches_session_ids(
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
            },
            [session_id],
        )

        self._assert_query_matches_session_ids(
            {
                "properties": [
                    {
                        "key": "name",
                        "value": ["org one"],
                        "operator": "exact",
                        "type": "group",
                        "group_type_index": 1,
                    }
                ],
            },
            [session_id],
        )

        self._assert_query_matches_session_ids(
            {
                "properties": [
                    {
                        "key": "name",
                        "value": ["org one"],
                        "operator": "exact",
                        "type": "group",
                        "group_type_index": 2,
                    }
                ],
            },
            [],
        )

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
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

        self._assert_query_matches_session_ids(
            {"order": "start_time"},
            [session_id_three, session_id_one, session_id_two],
            sort_results_when_asserting=False,
        )

        self._assert_query_matches_session_ids(
            {"order": "mouse_activity_count"},
            [session_id_two, session_id_one, session_id_three],
            sort_results_when_asserting=False,
        )

    @also_test_with_materialized_columns(event_properties=["$host"], verify_no_jsonextract=False)
    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_top_level_event_host_property_test_account_filter(self):
        """
        This is a regression test. See: https://posthoghelp.zendesk.com/agent/tickets/18059
        """
        self.team.test_account_filters = [
            {"key": "$host", "type": "event", "value": "^(localhost|127\\.0\\.0\\.1)($|:)", "operator": "not_regex"},
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
        # the session needs to have multiple matching or not matching events
        for _ in range(10):
            create_event(
                team=self.team,
                distinct_id="user",
                timestamp=self.an_hour_ago,
                properties={
                    "$session_id": "1",
                    "$window_id": "1",
                    "$host": "localhost",
                },
            )

        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
            click_count=10,
        )

        for _ in range(10):
            create_event(
                team=self.team,
                distinct_id="user2",
                timestamp=self.an_hour_ago,
                properties={
                    "$session_id": "2",
                    "$window_id": "1",
                    "$host": "example.com",
                },
            )
        produce_replay_summary(
            distinct_id="user2",
            session_id="2",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            click_count=10,
        )

        # there are 2 pageviews
        self._assert_query_matches_session_ids(
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
            },
            ["1", "2"],
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
                # only 1 pageview that matches the test_accounts filter
                "filter_test_accounts": True,
            }
        )

        assert session_recordings == [
            {
                "active_seconds": 0.0,
                "activity_score": 0.28,
                "click_count": 10,  # in the bug this value was 10 X number of events in the session
                "console_error_count": 0,
                "console_log_count": 0,
                "console_warn_count": 0,
                "distinct_id": "user2",
                "duration": 3600,
                "end_time": ANY,
                "first_url": "https://not-provided-by-test.com",
                "inactive_seconds": 3600.0,
                "keypress_count": 0,
                "mouse_activity_count": 0,
                "session_id": "2",
                "start_time": ANY,
                "team_id": self.team.id,
                "ongoing": 1,
            }
        ]

    @parameterized.expand(
        [
            ("single_distinct_id", ["test-user-1"], ["session1"]),
            ("multiple_distinct_ids", ["test-user-1", "test-user-2"], ["session1", "session2"]),
            ("non_existent_distinct_id", ["non-existent-user"], []),
            ("empty_distinct_ids", [], ["session1", "session2"]),
        ]
    )
    @snapshot_clickhouse_queries
    def test_filter_by_distinct_ids(self, name: str, distinct_ids: list[str], expected_sessions: list[str]):
        # Create two users with different distinct_ids
        user1 = "test-user-1"
        user2 = "test-user-2"
        Person.objects.create(team=self.team, distinct_ids=[user1])
        Person.objects.create(team=self.team, distinct_ids=[user2])

        # Create sessions for each user
        session1 = f"session1-{uuid4()}"
        session2 = f"session2-{uuid4()}"

        # Create session recordings
        produce_replay_summary(
            distinct_id=user1,
            session_id=session1,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.pk,
        )

        produce_replay_summary(
            distinct_id=user2,
            session_id=session2,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.pk,
        )

        # Map the test's generic session names to actual UUIDs
        session_map = {"session1": session1, "session2": session2}
        expected = [session_map[session] for session in expected_sessions]

        # Test filtering
        self._assert_query_matches_session_ids(query={"distinct_ids": distinct_ids}, expected=expected)

    @also_test_with_materialized_columns(person_properties=["email"], verify_no_jsonextract=False)
    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_filter_users_from_excluded_cohort(self):
        """
        Test that sessions from users in a cohort marked as excluded in team test account filters are properly filtered out.
        """
        # Create users
        internal_user = _create_person(
            distinct_ids=["internal_user"],
            team_id=self.team.pk,
            properties={"$is_internal": "yes"},
        )
        actual_user = _create_person(
            distinct_ids=["actual_user"],
            team_id=self.team.pk,
            properties={"$is_internal": "no"},
        )
        # Include internal user in the cohort
        internal_users_cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$is_internal", "value": "yes", "type": "person"}]}],
            name="internal_users_cohort",
        )
        flush_persons_and_events()
        internal_users_cohort.calculate_people_ch(pending_version=0)
        # Check that only internal user is in the cohort
        results = get_person_ids_by_cohort_id(self.team.pk, internal_users_cohort.id)
        assert len(results) == 1
        assert results[0] == str(internal_user.uuid)
        assert results[0] != str(actual_user.uuid)
        # Set up test account filters to exclude the cohort
        self.team.test_account_filters = [
            {
                "key": "id",
                "value": internal_users_cohort.pk,
                "operator": "not_in",
                "type": "cohort",
            }
        ]
        self.team.save()
        # Create replay summaries for both users
        produce_replay_summary(
            distinct_id="internal_user",
            session_id="internal_session",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        create_event(
            team=self.team,
            distinct_id="internal_user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "internal_session",
                "$window_id": "1",
            },
        )
        produce_replay_summary(
            distinct_id="internal_user",
            session_id="internal_session",
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id="actual_user",
            session_id="actual_session",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        create_event(
            team=self.team,
            distinct_id="actual_user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "actual_session",
                "$window_id": "1",
            },
        )
        produce_replay_summary(
            distinct_id="actual_user",
            session_id="actual_session",
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
        )
        # Check that both sessions are returned when filter_test_accounts is False
        self._assert_query_matches_session_ids(
            {
                "filter_test_accounts": False,
            },
            ["internal_session", "actual_session"],
        )
        # Check that only the regular session is returned when filter_test_accounts is True
        self._assert_query_matches_session_ids(
            {
                "filter_test_accounts": True,
            },
            ["actual_session"],
        )

    @also_test_with_materialized_columns(person_properties=["email"], verify_no_jsonextract=False)
    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_filter_users_from_excluded_cohort_no_events(self):
        """
        Test that sessions from users in a cohort marked as excluded in team test account filters are properly filtered out,
        even when the session recording don't have any events.
        """
        # Create users
        internal_user = _create_person(
            distinct_ids=["internal_user"],
            team_id=self.team.pk,
            properties={"$is_internal": "yes"},
        )
        actual_user = _create_person(
            distinct_ids=["actual_user"],
            team_id=self.team.pk,
            properties={"$is_internal": "no"},
        )
        # Include internal user in the cohort
        internal_users_cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$is_internal", "value": "yes", "type": "person"}]}],
            name="internal_users_cohort",
        )
        flush_persons_and_events()
        internal_users_cohort.calculate_people_ch(pending_version=0)
        # Check that only internal user is in the cohort
        results = get_person_ids_by_cohort_id(self.team.pk, internal_users_cohort.id)
        assert len(results) == 1
        assert results[0] == str(internal_user.uuid)
        assert results[0] != str(actual_user.uuid)
        # Set up test account filters to exclude the cohort
        self.team.test_account_filters = [
            {
                "key": "id",
                "value": internal_users_cohort.pk,
                "operator": "not_in",
                "type": "cohort",
            }
        ]
        self.team.save()
        # Create replay summaries for both users, but don't create events
        produce_replay_summary(
            distinct_id="internal_user",
            session_id="internal_session",
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id="actual_user",
            session_id="actual_session",
            team_id=self.team.id,
        )
        # Check that both sessions are returned when filter_test_accounts is False
        self._assert_query_matches_session_ids(
            {
                "filter_test_accounts": False,
            },
            ["internal_session", "actual_session"],
        )
        # The assumption is that if the recording has no events - it would still be able to identify what sessions to filter out
        self._assert_query_matches_session_ids(
            {
                "filter_test_accounts": True,
            },
            ["actual_session"],
        )
