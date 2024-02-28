from posthog.clickhouse.client import sync_execute
from posthog.test.base import (
    ClickhouseDestroyTablesMixin,
    _create_event,
)


class TestSessionsModel(ClickhouseDestroyTablesMixin):
    def test_it_creates_session_when_creating_event(self):
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="d1",
            properties={"$current_url": "/", "$session_id": "s1"},
        )

        response = sync_execute(
            """
            select *
            from sessions
            where
                distinct_id = %(distinct_id)s
                """,
            {
                "distinct_id": "d1",
            },
        )

        self.assertEqual(len(response), 1)
