from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from posthog.hogql import ast
from posthog.hogql.visitor import clear_locations
from posthog.models.utils import UUIDT
from posthog.schema import ReplayActiveHoursQuery
from posthog.session_recordings.queries.replay_active_hours_query_runner import ReplayActiveHoursQueryRunner
from posthog.session_recordings.queries.test.test_session_replay_events import produce_replay_summary
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, flush_persons_and_events


class TestReplayActiveHoursQueryRunner(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_runner(self, query: ReplayActiveHoursQuery) -> ReplayActiveHoursQueryRunner:
        return ReplayActiveHoursQueryRunner(team=self.team, query=query)

    def _create_session_replay_events(self, timestamp: str, session_id: Optional[str] = None) -> None:
        if session_id is None:
            session_id = f"test-session-{UUIDT()}"

        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk,
            first_timestamp=timestamp,
            last_timestamp=timestamp,
            distinct_id="test-user",
            first_url="https://example.io/home",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
        )
        flush_persons_and_events()

    def test_query_structure(self):
        runner = self._create_runner(ReplayActiveHoursQuery(source=None))
        query = runner.to_query()
        query = clear_locations(query)

        # Verify the basic structure of the query
        assert isinstance(query, ast.SelectQuery)
        assert query.select is not None
        assert len(query.select) == 8  # hour_block + 7 days
        assert query.select_from is not None
        assert isinstance(query.select_from, ast.JoinExpr)
        assert query.select_from.table is not None
        assert isinstance(query.select_from.table, ast.SelectQuery)
        assert query.group_by is not None
        assert len(query.group_by) == 1
        assert query.order_by is not None
        assert len(query.order_by) == 1

    def test_active_hours_calculation(self):
        # Create events for today and yesterday
        today = datetime.now(ZoneInfo("UTC"))
        yesterday = today - timedelta(days=1)

        # Create a session at 2:30 AM today
        self._create_session_replay_events(
            timestamp=today.replace(hour=2, minute=30).isoformat(), session_id="session-1"
        )

        # Create a session at 6:45 AM today
        self._create_session_replay_events(
            timestamp=today.replace(hour=6, minute=45).isoformat(), session_id="session-2"
        )

        # Create a session at 10:15 AM yesterday
        self._create_session_replay_events(
            timestamp=yesterday.replace(hour=10, minute=15).isoformat(), session_id="session-3"
        )

        runner = self._create_runner(ReplayActiveHoursQuery(source=None))
        response = runner.calculate()

        # Verify the results
        assert response.results is not None

        # Convert results to a more easily accessible format
        hour_blocks = {row[0]: row for row in response.results}

        # Today's 0-4 hour block should have 1 session
        assert hour_blocks[0][1] == 1  # Day 0, hour block 0

        # Today's 4-8 hour block should have 1 session
        assert hour_blocks[4][1] == 1  # Day 0, hour block 4

        # Yesterday's 8-12 hour block should have 1 session
        assert hour_blocks[8][2] == 1  # Day -1, hour block 8

    def test_empty_results(self):
        # Create events outside the 7-day window
        old_date = datetime.now(ZoneInfo("UTC")) - timedelta(days=8)
        self._create_session_replay_events(timestamp=old_date.isoformat(), session_id="old-session")

        runner = self._create_runner(ReplayActiveHoursQuery(source=None))
        response = runner.calculate()

        # Should return empty results since all events are outside the window
        assert len(response.results) == 0

    def test_multiple_sessions_same_hour_block(self):
        today = datetime.now(ZoneInfo("UTC"))

        # Create 3 sessions in the same 4-hour block (0-4)
        for i in range(3):
            self._create_session_replay_events(
                timestamp=today.replace(hour=1, minute=30).isoformat(), session_id=f"session-{i}"
            )

        runner = self._create_runner(ReplayActiveHoursQuery(source=None))
        response = runner.calculate()

        # Convert results to a more easily accessible format
        hour_blocks = {row[0]: row for row in response.results}

        # Should have 3 sessions in the 0-4 hour block for today
        assert hour_blocks[0][1] == 3  # Day 0, hour block 0
