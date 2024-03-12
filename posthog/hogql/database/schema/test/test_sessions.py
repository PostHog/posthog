from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
)


class TestReferringDomainType(ClickhouseTestMixin, APIBaseTest):
    def test_select_star(self):
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com", "$session_id": "s1"},
        )

        response = execute_hogql_query(
            parse_select(
                "select * from sessions",
            ),
            self.team,
        )

        self.assertEqual(
            len(response.results or []),
            1,
        )
