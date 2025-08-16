from typing import Literal
from uuid import uuid4

from freezegun import freeze_time
from parameterized import parameterized

from posthog.models import Person
from posthog.session_recordings.queries.test.listing_recordings.base_test_session_recordings_list import (
    BaseTestSessionRecordingsList,
)
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.base import snapshot_clickhouse_queries


class TestSessionRecordingListConsoleFilters(BaseTestSessionRecordingsList):
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

        # (session_recordings, _, _) = self.filter_recordings_by({"console_logs": ["info"]})

        (session_recordings, _, _) = self.filter_recordings_by(
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

        self.assert_query_matches_session_ids(
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

        (session_recordings, _, _) = self.filter_recordings_by(
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

        self.assert_query_matches_session_ids(
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

        (session_recordings, _, _) = self.filter_recordings_by(
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

        self.assert_query_matches_session_ids(
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

        self.assert_query_matches_session_ids(
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

        self.assert_query_matches_session_ids(
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
            (
                "OR operand, message 4 matches in warn and error",
                '[{"key": "level", "value": ["warn", "error"], "operator": "exact", "type": "log_entry"}, {"key": "message", "value": "message 4", "operator": "icontains", "type": "log_entry"}]',
                "OR",
                ["with-errors-session", "with-two-session", "with-warns-session", "with-logs-session"],
            ),
            (
                "AND operand, message 4 matches in log, warn, and error",
                '[{"key": "level", "value": ["warn", "error"], "operator": "exact", "type": "log_entry"}, {"key": "message", "value": "message 4", "operator": "icontains", "type": "log_entry"}]',
                "AND",
                ["with-errors-session", "with-two-session", "with-warns-session"],
            ),
            (
                "AND operand, message 5 matches only in warn",
                '[{"key": "level", "value": ["warn", "error"], "operator": "exact", "type": "log_entry"}, {"key": "message", "value": "message 5", "operator": "icontains", "type": "log_entry"}]',
                "AND",
                ["with-warns-session"],
            ),
            (
                "AND operand, message 5 does not match log level info",
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
        _name: str,
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

        self.assert_query_matches_session_ids(
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

        self.assert_query_matches_session_ids(
            {
                "having_predicates": '[{"key": "snapshot_source", "value": ["web"], "operator": "exact", "type": "recording"}]'
            },
            [session_id_one],
        )

        self.assert_query_matches_session_ids(
            {
                "having_predicates": '[{"key": "snapshot_source", "value": ["mobile"], "operator": "exact", "type": "recording"}]'
            },
            [session_id_two],
        )
