from datetime import datetime

from freezegun import freeze_time

from posthog.clickhouse.client import sync_execute
from posthog.hogql.query import execute_hogql_query
from posthog.models.raw_sessions.sql import DROP_RAW_SESSION_TABLE_SQL, RAW_SESSIONS_TABLE_SQL
from posthog.models.utils import uuid7
from posthog.schema import HogQLQueryModifiers, SessionTableVersion
from posthog.tasks.backfill_raw_sessions_table import run_backfill_raw_sessions_table_for_day, get_days_to_backfill
from posthog.test.base import APIBaseTest, _create_event


class TestBackfillRawSessionsTable(APIBaseTest):
    @freeze_time("2024-07-26T09:00:00Z")
    def test_schedule_feature_flag_multiple_changes(self) -> None:
        modifiers = HogQLQueryModifiers(sessionTableVersion=SessionTableVersion.V2)

        s1 = str(uuid7())
        s2 = str(uuid7())

        # create some events
        _create_event(
            event="pageview",
            distinct_id=s1,
            team=self.team,
            properties={"$session_id": s1},
        )
        _create_event(
            event="pageview",
            distinct_id=s2,
            team=self.team,
            properties={"$session_id": s2},
        )
        results = execute_hogql_query("SELECT id FROM sessions", team=self.team, modifiers=modifiers).results
        assert len(results) == 2

        # delete those sessions, so we can backfill them
        sync_execute(DROP_RAW_SESSION_TABLE_SQL())
        sync_execute(RAW_SESSIONS_TABLE_SQL())
        results = execute_hogql_query("SELECT id FROM sessions", team=self.team, modifiers=modifiers).results
        assert len(results) == 0

        # backfill sessions
        run_backfill_raw_sessions_table_for_day(datetime(2024, 7, 26), team_id=self.team.pk)

        # check that the sessions exist
        results = execute_hogql_query("SELECT id FROM sessions", team=self.team, modifiers=modifiers).results
        assert len(results) == 2

    def test_get_dates_are_inclusive(self):
        start_date = datetime(2022, 1, 1)
        end_date = datetime(2022, 1, 3)
        dates = get_days_to_backfill(start_date, end_date)
        assert len(dates) == 3
        assert dates == [datetime(2022, 1, 3), datetime(2022, 1, 2), datetime(2022, 1, 1)]
