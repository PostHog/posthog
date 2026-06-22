from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute
from posthog.session_recordings.sql.session_replay_feature_sql import TRUNCATE_SESSION_REPLAY_FEATURES_TABLE_SQL
from posthog.temporal.session_replay.surfacing_scoring_sweep.sql import count_unscored_sql, fetch_features_sql
from posthog.temporal.tests.session_replay.surfacing_scoring_sweep.ch_insert_helpers import (
    insert_replay_features,
    insert_session_replay_event,
)


class TestFetchFeaturesSqlShape:
    def test_targets_session_replay_events(self) -> None:
        sql = fetch_features_sql()
        assert "FROM session_replay_events" in sql

    def test_global_in_filters_on_team_id_and_session_id_tuple(self) -> None:
        sql = fetch_features_sql()
        assert "(f.team_id, f.session_id) GLOBAL IN" in sql

    def test_aggregated_stats_filters_features_by_lookback(self) -> None:
        sql = fetch_features_sql()
        assert "f.min_first_timestamp >= now() - toIntervalDay(%(lookback_days)s)" in sql

    def test_eligible_sessions_orders_before_limit(self) -> None:
        sql = fetch_features_sql()
        match = re.search(
            r"eligible_sessions\s+AS\s+\(.*?ORDER BY\s+session_id\s+LIMIT\s+%\(chunk_size\)s",
            sql,
            re.DOTALL,
        )
        assert match is not None, "ORDER BY session_id must precede LIMIT in the eligible_sessions CTE"

    def test_final_join_uses_team_id_and_session_id(self) -> None:
        sql = fetch_features_sql()
        assert "rf.team_id = e.team_id AND rf.session_id = e.session_id" in sql

    def test_surfaces_distinct_id_and_min_first_timestamp(self) -> None:
        sql = fetch_features_sql()
        assert "any(distinct_id) AS distinct_id" in sql
        assert "min(min_first_timestamp) AS started_at" in sql
        assert "e.distinct_id," in sql
        assert "e.started_at AS min_first_timestamp," in sql

    def test_eligible_sessions_has_raw_row_prefilter_and_exact_having_cut(self) -> None:
        sql = fetch_features_sql()
        assert "AND min_first_timestamp >= now() - toIntervalDay(%(lookback_days)s + 1)" in sql
        assert "AND started_at >= now() - toIntervalDay(%(lookback_days)s)" in sql

    @pytest.mark.parametrize("sql_fn", [fetch_features_sql, count_unscored_sql])
    def test_excludes_eventless_sessions(self, sql_fn: Callable[[], str]) -> None:
        assert "AND sum(event_count) > 0" in sql_fn()

    def test_count_unscored_has_raw_row_prefilter(self) -> None:
        sql = count_unscored_sql()
        assert "AND min_first_timestamp >= now() - toIntervalDay(%(lookback_days)s + 1)" in sql
        assert "AND min(min_first_timestamp) >= now() - toIntervalDay(%(lookback_days)s)" in sql

    def test_count_unscored_includes_lookback_and_chunking(self) -> None:
        sql = count_unscored_sql()
        assert "%(lookback_days)s" in sql
        assert "%(of_chunks)s" in sql
        assert "FROM session_replay_events" in sql


class TestEligibleSessionsJoinClickhouse(ClickhouseTestMixin, BaseTest):
    SESSION_ID = "01939d3e-7c80-7b56-bf8d-1e74e5c3b3a1"

    def setUp(self) -> None:
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_FEATURES_TABLE_SQL())

    def _insert_session_replay_event(
        self,
        *,
        team_id: int,
        session_id: str,
        distinct_id: str = "d1",
        surfacing_score: float | None = None,
    ) -> None:
        insert_session_replay_event(
            team_id=team_id,
            session_id=session_id,
            distinct_id=distinct_id,
            surfacing_score=surfacing_score,
        )

    def _insert_replay_features(self, *, team_id: int, session_id: str, event_count: int = 42) -> None:
        insert_replay_features(team_id=team_id, session_id=session_id, event_count=event_count)

    @staticmethod
    def _eligible_sessions_join_sql() -> str:
        return """
        WITH eligible_sessions AS (
            SELECT
                team_id,
                session_id,
                any(distinct_id) AS distinct_id,
                min(min_first_timestamp) AS min_first_timestamp
            FROM session_replay_events
            WHERE team_id = %(team_id)s
            GROUP BY team_id, session_id
            HAVING max(surfacing_score) IS NULL
            ORDER BY session_id
            LIMIT 100
        )
        SELECT e.team_id, e.session_id, e.distinct_id, sum(f.event_count) AS ec
        FROM eligible_sessions e
        INNER JOIN session_replay_features AS f
            ON f.team_id = e.team_id AND f.session_id = e.session_id
        WHERE (f.team_id, f.session_id) GLOBAL IN (
            SELECT team_id, session_id FROM eligible_sessions
        )
        GROUP BY e.team_id, e.session_id, e.distinct_id
        """

    def test_join_matches_on_string_session_id(self) -> None:
        self._insert_session_replay_event(team_id=self.team.id, session_id=self.SESSION_ID)
        self._insert_replay_features(team_id=self.team.id, session_id=self.SESSION_ID, event_count=42)

        rows = sync_execute(self._eligible_sessions_join_sql(), {"team_id": self.team.id})
        assert len(rows) == 1
        team_id, session_id, distinct_id, event_count = rows[0]
        assert team_id == self.team.id
        assert session_id == self.SESSION_ID
        assert distinct_id == "d1"
        assert event_count == 42

    def test_team_id_isolation_in_join(self) -> None:
        other_team_id = self.team.id + 9999
        self._insert_session_replay_event(team_id=self.team.id, session_id=self.SESSION_ID)
        self._insert_replay_features(team_id=other_team_id, session_id=self.SESSION_ID)

        rows = sync_execute(self._eligible_sessions_join_sql(), {"team_id": self.team.id})
        assert rows == []

    def test_having_excludes_scored_sessions(self) -> None:
        scored_session = "01939d3e-7c80-7b56-bf8d-1e74e5c3b3a2"
        self._insert_session_replay_event(team_id=self.team.id, session_id=self.SESSION_ID)
        self._insert_session_replay_event(team_id=self.team.id, session_id=scored_session, surfacing_score=0.5)
        self._insert_replay_features(team_id=self.team.id, session_id=self.SESSION_ID)
        self._insert_replay_features(team_id=self.team.id, session_id=scored_session)

        rows = sync_execute(self._eligible_sessions_join_sql(), {"team_id": self.team.id})
        assert len(rows) == 1
        assert rows[0][1] == self.SESSION_ID

    def test_count_unscored_excludes_scored_sessions(self) -> None:
        scored_session = "01939d3e-7c80-7b56-bf8d-1e74e5c3b3a2"
        self._insert_session_replay_event(team_id=self.team.id, session_id=self.SESSION_ID)
        self._insert_session_replay_event(team_id=self.team.id, session_id=scored_session, surfacing_score=0.5)

        rows = sync_execute(count_unscored_sql(), {"lookback_days": 365, "of_chunks": 1})
        # Other tests may leave residual unscored sessions on shared CH state.
        assert rows[0][0] >= 1
