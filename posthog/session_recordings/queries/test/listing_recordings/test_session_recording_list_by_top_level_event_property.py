from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from parameterized import parameterized, parameterized_class

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.log_entries import TRUNCATE_LOG_ENTRIES_TABLE_SQL
from posthog.models import EventProperty, Person
from posthog.models.action import Action
from posthog.models.team import Team
from posthog.models.utils import uuid7
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingQueryResult
from posthog.session_recordings.queries.test.listing_recordings.test_utils import (
    assert_query_matches_session_ids,
    create_event,
    filter_recordings_by,
)
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL


@parameterized_class([{"allow_event_property_expansion": True}, {"allow_event_property_expansion": False}])
@freeze_time("2021-01-01T13:46:23")
class TestSessionRecordingsListByTopLevelEventProperty(ClickhouseTestMixin, APIBaseTest):
    # set by parameterized_class decorator
    allow_event_property_expansion: bool

    def setUp(self):
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())
        sync_execute(TRUNCATE_LOG_ENTRIES_TABLE_SQL)

        EventProperty.objects.all().delete()

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
            team=self.team,
            query=query,
            expected=expected,
            sort_results_when_asserting=sort_results_when_asserting,
            allow_event_property_expansion=self.allow_event_property_expansion,
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

    @parameterized.expand(
        [
            (
                "session 1 matches target flag is True",
                [{"type": "event", "key": "$feature/target-flag", "operator": "exact", "value": ["true"]}],
                ["1"],
            ),
            (
                "session 2 matches target flag is False",
                [{"type": "event", "key": "$feature/target-flag", "operator": "exact", "value": ["false"]}],
                ["2"],
            ),
            (
                "sessions 1 and 2 match target flag is set",
                [{"type": "event", "key": "$feature/target-flag", "operator": "is_set", "value": "is_set"}],
                ["1", "2"],
            ),
            (
                "sessions 3 and 4 match target flag is not set",
                [{"type": "event", "key": "$feature/target-flag", "operator": "is_not_set", "value": "is_not_set"}],
                ["3", "4"],
            ),
        ]
    )
    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_can_filter_for_flags(self, _name: str, properties: dict, expected: list[str]) -> None:
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

        for event_name in ["foo", "bar", "baz", "$pageview"]:
            EventProperty.objects.create(team=self.team, event=event_name, property="$feature/target-flag")
            EventProperty.objects.create(team=self.team, event=event_name, property="$feature/flag-that-is-different")

        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )
        create_event(
            event_name="foo",
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "1",
                "$window_id": "1",
                "$feature/target-flag": True,
            },
        )

        produce_replay_summary(
            distinct_id="user",
            session_id="2",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )
        create_event(
            event_name="bar",
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "2",
                "$window_id": "1",
                "$feature/target-flag": False,
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
            event_name="baz",
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "3",
                "$window_id": "1",
                "$feature/flag-that-is-different": False,
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
            event_name="foo",
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "4",
                "$window_id": "1",
            },
        )

        self._assert_query_matches_session_ids({"properties": properties}, expected)

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_can_filter_for_two_is_not_event_properties(self) -> None:
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

        for event_name in ["foo", "bar", "baz", "$pageview"]:
            EventProperty.objects.create(team=self.team, event=event_name, property="probe-one")
            EventProperty.objects.create(team=self.team, event=event_name, property="probe-two")
            EventProperty.objects.create(team=self.team, event=event_name, property="$feature/target-flag-2")

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

        self._assert_query_matches_session_ids(
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

        for event_name in ["foo", "bar", "baz", "$pageview"]:
            EventProperty.objects.create(team=self.team, event=event_name, property="$host")
            EventProperty.objects.create(team=self.team, event=event_name, property="something-else")

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

        self._assert_query_matches_session_ids(
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

        for event_name in ["foo", "bar", "baz", "$pageview"]:
            EventProperty.objects.create(team=self.team, event=event_name, property="something")
            EventProperty.objects.create(team=self.team, event=event_name, property="has")
            EventProperty.objects.create(team=self.team, event=event_name, property="something-else")

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

        self._assert_query_matches_session_ids(
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
