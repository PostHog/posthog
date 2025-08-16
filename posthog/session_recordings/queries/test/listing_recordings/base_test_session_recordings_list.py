from dateutil.relativedelta import relativedelta
from django.utils.timezone import now

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.log_entries import TRUNCATE_LOG_ENTRIES_TABLE_SQL
from posthog.models import Person
from posthog.models.action import Action
from posthog.models.team import Team
from posthog.schema import RecordingsQuery
from posthog.session_recordings.queries.session_recording_list_from_query import (
    SessionRecordingQueryResult,
    SessionRecordingListFromQuery,
)
from posthog.session_recordings.queries.test.listing_recordings.test_utils import (
    create_event,
)
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.session_recording_api import query_as_params_to_dict
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


class BaseTestSessionRecordingsList(ClickhouseTestMixin, APIBaseTest):
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

    def filter_recordings_by(self, recordings_filter: dict | None = None) -> SessionRecordingQueryResult:
        the_query = RecordingsQuery.model_validate(query_as_params_to_dict(recordings_filter or {}))
        session_recording_list_instance = SessionRecordingListFromQuery(
            query=the_query, team=self.team, hogql_query_modifiers=None
        )
        return session_recording_list_instance.run()

    def assert_query_matches_session_ids(
        self, query: dict | None, expected: list[str], sort_results_when_asserting: bool = True
    ) -> None:
        (session_recordings, more_recordings_available, _) = self.filter_recordings_by(recordings_filter=query)

        # in some tests we care about the order of results e.g. when testing sorting
        # generally we want to sort results since the order is not guaranteed
        # e.g. we're using UUIDs for the IDs
        if sort_results_when_asserting:
            assert sorted([sr["session_id"] for sr in session_recordings]) == sorted(expected)
        else:
            assert [sr["session_id"] for sr in session_recordings] == expected

        assert more_recordings_available is False
