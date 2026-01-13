from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.helpers.team_id_filter_visitor import list_team_id_filters
from posthog.hogql.parser import parse_select


class TestTeamIdFilterVisitor(BaseTest):
    @parameterized.expand(
        [
            (
                "SELECT * FROM events WHERE team_id = 1",
                {"events"},
                set(),
            ),
            (
                "SELECT * FROM events WHERE events.team_id = 1",
                {"events"},
                set(),
            ),
            (
                "SELECT * FROM events e JOIN persons p ON e.person_id = p.id WHERE e.team_id = 1",
                {"events"},
                {"persons"},
            ),
            (
                "SELECT * FROM events e JOIN persons p ON p.team_id = 1",
                {"persons"},
                {"events"},
            ),
            (
                "SELECT * FROM events e JOIN persons p ON p.team_id = 1 WHERE equals(e.team_id, 1)",
                {"events", "persons"},
                set(),
            ),
            (
                "SELECT * FROM events WHERE team_id = 1 UNION ALL SELECT * FROM persons",
                {"events"},
                {"persons"},
            ),
            (
                "SELECT argMax(uuid, timestamp) FROM events WHERE event = 'survey sent' AND JSONExtractString(properties, '$survey_id') = 'x' OR '1'='1' AND team_id = 271699",
                set(),  # THIS should fail, nothing with the guard
                {"events"},
            ),
        ]
    )
    def test_list_team_id_filters(
        self,
        query: str,
        expected_with_team_id: set[str],
        expected_without_team_id: set[str],
    ) -> None:
        parsed = parse_select(query)
        result = list_team_id_filters(parsed)

        self.assertEqual(result.with_team_id, expected_with_team_id)
        self.assertEqual(result.without_team_id, expected_without_team_id)
