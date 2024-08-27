from posthog.clickhouse.client import sync_execute
from posthog.models.raw_sessions.sql import RAW_SESSION_TABLE_BACKFILL_SELECT_SQL
from posthog.models.utils import uuid7
from posthog.test.base import (
    _create_event,
    ClickhouseTestMixin,
    BaseTest,
)


class TestRawSessionsModel(ClickhouseTestMixin, BaseTest):
    def test_backfill_sql(self):
        distinct_id = str(uuid7())
        session_id = str(uuid7())
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            properties={"$current_url": "/", "$session_id": session_id},
            timestamp="2024-03-08",
        )

        # just test that the backfill SQL can be run without error
        sync_execute(
            "INSERT INTO raw_sessions" + RAW_SESSION_TABLE_BACKFILL_SELECT_SQL() + "AND team_id = %(team_id)s",
            {"team_id": self.team.id},
        )
