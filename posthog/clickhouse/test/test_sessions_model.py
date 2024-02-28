from posthog.clickhouse.client import sync_execute
from posthog.test.base import (
    _create_event,
    BaseTest,
)


class TestSessionsModel(BaseTest):
    def test_it_creates_session_when_creating_event(self):
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="d1",
            properties={"$current_url": "/", "$session_id": "s1"},
        )

        response = sync_execute(
            """
            select
                session_id,
                distinct_id
            from sessions_v
            where
                distinct_id = %(distinct_id)s AND
                team_id = %(team_id)s
                """,
            {
                "distinct_id": "d1",
                "team_id": self.team.id,
            },
        )

        self.assertEqual(len(response), 1)
