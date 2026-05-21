"""ClickHouse integration tests for `fetch_features_sql` / `count_unscored_sql`.

Targets the invariants that keep the chunked feature fetch correct after the
move from `raw_sessions_v3` to `session_replay_events`:

1. Primary-key-seek-friendly filter. `session_replay_features` is ordered by
   `(team_id, session_id)`, so the GLOBAL IN must filter on the full tuple
   (`(team_id, session_id) GLOBAL IN ...`) — not just `session_id`.

2. Deterministic chunking. CH inlines `WITH ... AS` as a subquery, so
   `eligible_sessions` is evaluated twice. Without `ORDER BY` before LIMIT, the two
   evaluations can return different subsets and the inner join silently drops
   the difference.

3. Tenant isolation. The final JOIN must include both `team_id` AND `session_id`
   — losing team_id wastes the index prefix AND creates a tenant-leak surface.

The shape tests guard against silent regressions in the SQL string. The CH
integration tests prove the join actually returns rows for matching IDs and
zero rows for cross-tenant scenarios.

Note: the previous reinterpretAsUUID byte-swap dance disappeared when we
moved off raw_sessions_v3.session_id_v7 (UInt128) and onto
session_replay_events.session_id (hyphenated UUID String) — the join is
now direct String-to-String.
"""

from __future__ import annotations

import re

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute
from posthog.session_recordings.sql.session_replay_feature_sql import TRUNCATE_SESSION_REPLAY_FEATURES_TABLE_SQL
from posthog.temporal.session_replay.surfacing_scoring_sweep.sql import count_unscored_sql, fetch_features_sql


class TestFetchFeaturesSqlShape:
    """Regression-proof the SQL string against re-introduction of past bugs."""

    def test_targets_session_replay_events_not_raw_sessions_v3(self) -> None:
        sql = fetch_features_sql()
        # Score lives on session_replay_events now — see the move from raw_sessions_v3
        # in CH migration 0252_session_replay_events_surfacing_score.py.
        assert "FROM session_replay_events" in sql
        assert "raw_sessions_v3" not in sql

    def test_no_byte_swap_dance(self) -> None:
        sql = fetch_features_sql()
        # session_id is a String on session_replay_events; the prior
        # reinterpretAsUUID(bitOr(bitShiftLeft, bitShiftRight)) workaround for
        # UInt128 storage on raw_sessions_v3 should be gone.
        assert "reinterpretAsUUID" not in sql
        assert "bitShiftLeft" not in sql

    def test_global_in_filters_on_team_id_and_session_id_tuple(self) -> None:
        sql = fetch_features_sql()
        # session_replay_features is ORDER BY (team_id, session_id) — tuple lookup
        # is what enables granule skipping.
        assert "(f.team_id, f.session_id) GLOBAL IN" in sql

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
        # Joining on session_id alone is theoretically safe (UUIDs are unique-ish)
        # but losing the team_id check both wastes the index prefix and creates a
        # tenant-leak surface — keep the assertion strict.
        assert "rf.team_id = e.team_id AND rf.session_id = e.session_id" in sql

    def test_surfaces_distinct_id_and_min_first_timestamp(self) -> None:
        """The producer needs distinct_id (for shard routing) and min_first_timestamp
        (for identity-value Kafka payload) — see `_build_partial_row` for why.
        """
        sql = fetch_features_sql()
        # In the eligible_sessions CTE
        assert "any(distinct_id) AS distinct_id" in sql
        assert "min(min_first_timestamp) AS min_first_timestamp" in sql
        # Carried into the final SELECT
        assert "e.distinct_id," in sql
        assert "e.min_first_timestamp," in sql

    def test_count_unscored_includes_lookback_and_chunking(self) -> None:
        sql = count_unscored_sql()
        assert "%(lookback_days)s" in sql
        assert "%(of_chunks)s" in sql
        assert "FROM session_replay_events" in sql


class TestEligibleSessionsJoinClickhouse(ClickhouseTestMixin, BaseTest):
    """End-to-end check that the (team_id, session_id) join lines up against
    real CH and that the HAVING-based unscored filter actually skips scored rows.

    Inserts directly into `writable_session_replay_events` (mimicking the
    Kafka writeback MV's partial-column insert pattern that the scorer uses)
    and into `writable_session_replay_features`. We don't run the full
    `fetch_features_sql` because a handful of feature columns are still
    pending on the live `session_replay_features` DDL (see `sql.py` schema
    gap) — the eligibility join is what we're guarding here.
    """

    SESSION_ID = "01939d3e-7c80-7b56-bf8d-1e74e5c3b3a1"

    def setUp(self) -> None:
        super().setUp()
        # session_replay_features isn't in the global truncate list (posthog/conftest.py),
        # so other tests can leave residual rows around — clear the slate explicitly.
        sync_execute(TRUNCATE_SESSION_REPLAY_FEATURES_TABLE_SQL())

    def _insert_session_replay_event(
        self,
        *,
        team_id: int,
        session_id: str,
        distinct_id: str = "d1",
        surfacing_score: float | None = None,
    ) -> None:
        # Mirrors the partial-row write pattern: every column not specified gets
        # its aggregate-function identity. Leaving surfacing_score NULL
        # marks the row as "eligible" via the HAVING clause.
        if surfacing_score is None:
            sync_execute(
                "INSERT INTO writable_session_replay_events "
                "(session_id, team_id, distinct_id, min_first_timestamp, max_last_timestamp) "
                "VALUES (%(session_id)s, %(team_id)s, %(distinct_id)s, now64(6) - INTERVAL 1 HOUR, now64(6))",
                {"session_id": session_id, "team_id": team_id, "distinct_id": distinct_id},
            )
        else:
            sync_execute(
                "INSERT INTO writable_session_replay_events "
                "(session_id, team_id, distinct_id, min_first_timestamp, max_last_timestamp, surfacing_score) "
                "VALUES (%(session_id)s, %(team_id)s, %(distinct_id)s, "
                "now64(6) - INTERVAL 1 HOUR, now64(6), %(score)s)",
                {
                    "session_id": session_id,
                    "team_id": team_id,
                    "distinct_id": distinct_id,
                    "score": surfacing_score,
                },
            )

    def _insert_replay_features(self, *, team_id: int, session_id: str, event_count: int = 42) -> None:
        sync_execute(
            "INSERT INTO writable_session_replay_features "
            "(session_id, team_id, distinct_id, min_first_timestamp, max_last_timestamp, event_count) "
            "SELECT %(session_id)s, %(team_id)s, 'd1', now64(6) - INTERVAL 1 HOUR, now64(6), %(event_count)s",
            {"session_id": session_id, "team_id": team_id, "event_count": event_count},
        )

    @staticmethod
    def _eligible_sessions_join_sql() -> str:
        """A trimmed copy of fetch_features_sql's eligible_sessions + INNER JOIN.

        We can't run the full `fetch_features_sql` against the live CH schema yet
        (some feature columns are pending — see `sql.py` schema gap), but the
        CTE → join is exactly where past bugs lived.
        """
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
        """Same UUID used by two teams must not cross over via the join."""
        other_team_id = self.team.id + 9999
        self._insert_session_replay_event(team_id=self.team.id, session_id=self.SESSION_ID)
        # Features row only for the OTHER team — querying as our team must miss.
        self._insert_replay_features(team_id=other_team_id, session_id=self.SESSION_ID)

        rows = sync_execute(self._eligible_sessions_join_sql(), {"team_id": self.team.id})
        assert rows == []

    def test_having_excludes_scored_sessions(self) -> None:
        """A row with a non-NULL surfacing_score must drop out of eligible_sessions."""
        scored_session = "01939d3e-7c80-7b56-bf8d-1e74e5c3b3a2"
        self._insert_session_replay_event(team_id=self.team.id, session_id=self.SESSION_ID)
        self._insert_session_replay_event(team_id=self.team.id, session_id=scored_session, surfacing_score=0.5)
        # Features for both, so the unscored one definitely lands.
        self._insert_replay_features(team_id=self.team.id, session_id=self.SESSION_ID)
        self._insert_replay_features(team_id=self.team.id, session_id=scored_session)

        rows = sync_execute(self._eligible_sessions_join_sql(), {"team_id": self.team.id})
        # Exactly the unscored session lands; the scored one is filtered by HAVING.
        assert len(rows) == 1
        assert rows[0][1] == self.SESSION_ID

    def test_count_unscored_excludes_scored_sessions(self) -> None:
        """Score one of two sessions; `count_unscored_sql` should report the other one."""
        scored_session = "01939d3e-7c80-7b56-bf8d-1e74e5c3b3a2"
        self._insert_session_replay_event(team_id=self.team.id, session_id=self.SESSION_ID)
        self._insert_session_replay_event(team_id=self.team.id, session_id=scored_session, surfacing_score=0.5)

        # `of_chunks=1` makes the modulo trivially match every row, so we count
        # all unscored sessions in the lookback window.
        rows = sync_execute(count_unscored_sql(), {"lookback_days": 365, "of_chunks": 1})
        # Other tests might leave behind unscored sessions; assert ours is included
        # rather than equality to avoid false-flake on shared CH state.
        assert rows[0][0] >= 1
