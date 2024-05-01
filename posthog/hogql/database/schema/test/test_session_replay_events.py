from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
)


class TestFilterSessionReplaysByConsoleLogs(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()

        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="d1",
            session_id="session_with_info_and_error_messages",
            log_messages={
                "info": ["This is an info message"],
                "error": ["This is a generic message"],
            },
        )

        produce_replay_summary(
            team_id=self.team.pk,
            distinct_id="d1",
            session_id="session_with_only_info_messages",
            log_messages={
                "info": ["This is a generic message"],
            },
        )

        produce_replay_summary(
            team_id=self.team.pk, distinct_id="d1", session_id="session_with_no_log_messages", log_messages=None
        )

    def test_select_by_console_log_text(self):
        response = execute_hogql_query(
            parse_select(
                "select session_id from raw_session_replay_events where console_logs.message = {log_message} order by session_id asc",
                placeholders={"log_message": ast.Constant(value="This is a generic message")},
            ),
            self.team,
        )

        assert response.results == [("session_with_info_and_error_messages",), ("session_with_only_info_messages",)]

    def test_select_by_console_log_text_and_level(self):
        response = execute_hogql_query(
            parse_select(
                "select session_id from raw_session_replay_events where console_logs.message = {log_message} and level = {log_level} order by session_id asc",
                placeholders={
                    "log_message": ast.Constant(value="This is a generic message"),
                    "log_level": ast.Constant(value="error"),
                },
            ),
            self.team,
        )

        assert response.results == [("session_with_info_and_error_messages",)]
