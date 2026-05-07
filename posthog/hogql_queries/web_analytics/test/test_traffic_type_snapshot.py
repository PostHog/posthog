from typing import Any

import pytest
from posthog.test.base import BaseTest, _create_event, flush_persons_and_events

from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import pretty_print_response_in_tests


@pytest.mark.usefixtures("unittest_snapshot")
class TestTrafficTypeSnapshot(BaseTest):
    snapshot: Any

    def _create_test_events(self):
        user_agents = [
            ("GPTBot/1.0", "bot"),
            ("Mozilla/5.0 Chrome/120.0", "human"),
            ("curl/7.64.1", "automation"),
            ("Googlebot/2.1", "search"),
        ]
        for ua, distinct_id in user_agents:
            _create_event(
                distinct_id=distinct_id,
                event="$pageview",
                team=self.team,
                properties={"$user_agent": ua},
            )
        flush_persons_and_events()

    def _run_function_query(self, function_name: str, alias: str):
        self._create_test_events()
        response = execute_hogql_query(
            f"""
            SELECT
                {function_name}(properties.$user_agent) as {alias},
                count() as count
            FROM events
            WHERE event = '$pageview'
            GROUP BY {alias}
            ORDER BY {alias}
            """,
            self.team,
        )
        assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot

    def test_get_traffic_type(self):
        self._run_function_query("__preview_getTrafficType", "traffic_type")

    def test_get_traffic_category(self):
        self._run_function_query("__preview_getTrafficCategory", "category")

    def test_is_bot(self):
        self._run_function_query("__preview_isBot", "is_bot")

    def test_get_bot_type(self):
        self._run_function_query("__preview_getBotType", "bot_type")

    def test_get_bot_name(self):
        self._run_function_query("__preview_getBotName", "bot_name")

    def test_filter_bots_sql_query(self):
        self._create_test_events()
        response = execute_hogql_query(
            """
            SELECT event, properties.$user_agent as user_agent
            FROM events
            WHERE event = '$pageview' AND NOT __preview_isBot(properties.$user_agent)
            ORDER BY user_agent
            """,
            self.team,
        )
        assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
