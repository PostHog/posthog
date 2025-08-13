from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.log_entries import TRUNCATE_LOG_ENTRIES_TABLE_SQL
from posthog.models import Person
from posthog.models.action import Action
from posthog.models.team import Team
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingQueryResult
from posthog.session_recordings.queries.test.listing_recordings.test_utils import (
    create_event,
    assert_query_matches_session_ids,
    filter_recordings_by,
)
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


@freeze_time("2021-01-01T13:46:23")
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

    def _filter_recordings_by(self, recordings_filter: dict | None = None) -> SessionRecordingQueryResult:
        return filter_recordings_by(team=self.team, recordings_filter=recordings_filter)

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
