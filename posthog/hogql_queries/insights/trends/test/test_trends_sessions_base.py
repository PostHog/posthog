from posthog.clickhouse.client import sync_execute
from posthog.models.raw_sessions.sql_v3 import RAW_SESSION_TABLE_BACKFILL_SQL_V3


class TrendsSessionsTestBase:
    """
    Base class for trends tests that query SessionsNode.

    Provides helper to populate raw_sessions table from events, since the
    materialized view doesn't run in tests.
    """

    def _populate_sessions_from_events(self, team_id: int | None = None):
        """
        Manually populate raw_sessions table from events.

        This is needed because in tests, the materialized view that normally
        populates raw_sessions doesn't run automatically. We use the backfill
        SQL which is the same SELECT statement used by the materialized view.
        """
        if team_id is None:
            team_id = self.team.pk

        # Use the backfill SQL - pass TRUE to get all events, the SELECT already filters by team
        backfill_sql = RAW_SESSION_TABLE_BACKFILL_SQL_V3(where="TRUE")
        try:
            sync_execute(backfill_sql)
        except Exception as e:
            # If backfill fails, provide helpful error message
            raise Exception(f"Failed to populate sessions from events for team {team_id}: {str(e)}") from e
