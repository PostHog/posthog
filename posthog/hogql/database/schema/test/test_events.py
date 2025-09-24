from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.utils import uuid7


class TestEvents(ClickhouseTestMixin, APIBaseTest):
    def test_select_star_from_events(self):
        session_id = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com", "$session_id": session_id},
        )

        response = execute_hogql_query(
            parse_select(
                "select * from events",
            ),
            team=self.team,
        )

        self.assertEqual(
            len(response.results or []),
            1,
        )
