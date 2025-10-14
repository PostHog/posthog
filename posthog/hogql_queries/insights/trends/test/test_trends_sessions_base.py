from posthog.clickhouse.client import sync_execute
from posthog.models.raw_sessions.sql import RAW_SESSION_TABLE_BACKFILL_SQL


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

        # Use the V2 backfill SQL to populate raw_sessions (not raw_sessions_v3)
        # SessionsTableV2 queries from raw_sessions, so we need to populate that table
        backfill_sql = RAW_SESSION_TABLE_BACKFILL_SQL()
        try:
            sync_execute(backfill_sql)
        except Exception as e:
            # If backfill fails, provide helpful error message
            raise Exception(f"Failed to populate sessions from events for team {team_id}: {str(e)}") from e
