"""End-to-end check that fetch → validate → predict works against real ClickHouse.

Booster comes from the `surfacing_booster_path` fixture (prod uses S3).
Catches SQL/booster schema drift the static `test_sql_alignment.py` can't —
specifically dtype-from-CH bugs.

Prereqs that the local CH database needs:
    * `surfacing_score` column on `session_replay_events` (added by an
      ALTER migration that ships alongside this test).
    * `session_replay_features` populated with at least the columns the model
      reads (every feature this test inserts is in the live DDL today).

What the test deliberately does NOT cover:
    * Kafka writeback (`_publish_scores`) — that's covered by `test_publish_scores.py`.
    * Multi-chunk fan-out — `test_score_chunk_activity_unit.py` would, the workflow
      shape itself is a separate test surface.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL
from posthog.session_recordings.sql.session_replay_feature_sql import TRUNCATE_SESSION_REPLAY_FEATURES_TABLE_SQL
from posthog.temporal.session_replay.surfacing_scoring_sweep.activities import _fetch_features_dataframe
from posthog.temporal.session_replay.surfacing_scoring_sweep.features import ID_COLUMNS, validate_features
from posthog.temporal.session_replay.surfacing_scoring_sweep.scorer import get_feature_names, predict
from posthog.temporal.session_replay.surfacing_scoring_sweep.types import ChunkSpec
from posthog.temporal.tests.session_replay.surfacing_scoring_sweep.ch_insert_helpers import insert_session_replay_event


@pytest.mark.usefixtures("surfacing_booster_path")
class TestScoreChunkPipelineClickhouse(ClickhouseTestMixin, BaseTest):
    """One realistic session, full pipeline, synthetic booster."""

    def setUp(self) -> None:
        super().setUp()
        # Both target tables aren't in posthog/conftest.py's truncate list —
        # other tests can leave residue around. Wipe them before every run so
        # the assertions on row counts / scores don't get poisoned.
        sync_execute(TRUNCATE_SESSION_REPLAY_FEATURES_TABLE_SQL())
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())

        # Fresh UUID per test → timestamp is "now-ish", which the SQL's
        # `min_first_timestamp >= now() - INTERVAL N DAY` filter requires.
        self.session_id: str = str(uuid.uuid4())
        self.distinct_id: str = "d1"
        self.session_start: datetime = datetime.now(tz=UTC) - timedelta(seconds=30)

    def _seed_unscored_session(self) -> None:
        """Insert a NULL-score session_replay_events row matching self.session_id.

        Mirrors what real ingestion writes (one chunk row with min/max timestamps)
        but leaves surfacing_score NULL so the HAVING filter picks the row up.
        """
        insert_session_replay_event(
            team_id=self.team.id,
            session_id=self.session_id,
            distinct_id=self.distinct_id,
            start=self.session_start,
        )

    def _seed_replay_features(self) -> None:
        """Insert one session_replay_features row with realistic-ish counts.

        Values are chosen to make every derived rate non-trivial (so the
        booster sees signal, not all-zeros) and to exercise both numerator
        and denominator inputs to each rate/ratio. Anything we don't insert
        defaults to 0 (SimpleAggregateFunction(sum, ...) initial state),
        which surfaces as NaN after a `nullIf(_, 0)` divide — which the
        validator passes through and XGBoost handles natively.
        """
        sync_execute(
            "INSERT INTO writable_session_replay_features ("
            "  session_id, team_id, distinct_id,"
            "  min_first_timestamp, max_last_timestamp,"
            # 30s session, lots of activity → non-zero rates
            "  event_count, click_count, keypress_count, mouse_activity_count,"
            "  scroll_event_count, page_visit_count, text_selection_count,"
            "  rage_click_count, dead_click_count, quick_back_count,"
            "  console_error_count, console_error_after_click_count,"
            "  network_request_count, network_failed_request_count,"
            # Mouse stats — sums match what'd come out of a real session
            "  mouse_position_count, mouse_sum_x, mouse_sum_x_squared,"
            "  mouse_sum_y, mouse_sum_y_squared,"
            "  mouse_distance_traveled, mouse_direction_change_count,"
            "  mouse_velocity_sum, mouse_velocity_sum_of_squares, mouse_velocity_count,"
            # Scroll stats
            "  total_scroll_magnitude, scroll_direction_reversal_count,"
            "  rapid_scroll_reversal_count, max_scroll_y,"
            # Action gap stats
            "  inter_action_gap_count, inter_action_gap_sum_ms,"
            "  inter_action_gap_sum_of_squares_ms, max_idle_gap_ms,"
            # Network duration stats
            "  network_request_duration_sum, network_request_duration_sum_of_squares,"
            "  network_request_duration_count"
            ") SELECT "
            "  %(session_id)s, %(team_id)s, %(distinct_id)s,"
            "  now64(6) - INTERVAL 30 SECOND, now64(6),"
            "  250, 12, 80, 200,"
            "  60, 5, 8,"
            "  0, 1, 2,"
            "  3, 1,"
            "  30, 1,"
            "  150, 75000, 45000000,"
            "  60000, 36000000,"
            "  4500.5, 30,"
            "  500.0, 2000.0, 50,"
            "  1200.0, 4, 1, 1800.0,"
            "  20, 5000.0, 1500000.0, 4500.0,"
            "  3000.0, 400000.0, 30",
            {"session_id": self.session_id, "team_id": self.team.id, "distinct_id": self.distinct_id},
        )

    def test_full_pipeline_produces_score_in_unit_interval(self) -> None:
        self._seed_unscored_session()
        self._seed_replay_features()

        # of_chunks=1 puts every session in the single bucket (cityHash64 % 1 = 0)
        # so we don't need to predict which bucket SESSION_ID lands in.
        spec = ChunkSpec(chunk_id=0, of_chunks=1, chunk_size=10, lookback_days=7)
        df = _fetch_features_dataframe(spec)

        feature_names = get_feature_names()

        # Shape contract: ID columns + every booster feature, exactly the row count we seeded.
        assert len(df) == 1, f"expected 1 row from the SELECT, got {len(df)}"
        for col in ID_COLUMNS:
            assert col in df.columns, f"id column {col!r} missing from SELECT output"
        for name in feature_names:
            assert name in df.columns, f"feature {name!r} missing from SELECT output"

        # ID columns must round-trip the values we seeded — these are what the
        # producer relies on (shard routing + identity-value timestamp).
        row = df.iloc[0]
        assert str(row["session_id"]) == self.session_id
        assert int(row["team_id"]) == self.team.id
        assert str(row["distinct_id"]) == self.distinct_id
        assert row["min_first_timestamp"] is not None

        # The validator is the same gate the production activity uses — if
        # this raises, the SQL drifted from the booster (which `test_sql_alignment.py`
        # would also catch, but proving it on real CH output covers dtype-from-CH bugs
        # the static test can't).
        validate_features(df, feature_names=feature_names)

        scores = predict(df)
        assert scores.shape == (1,)
        score = float(scores[0])
        assert 0.0 <= score <= 1.0, f"booster returned out-of-range score {score}"

    def test_session_without_replay_features_is_inner_joined_out(self) -> None:
        self._seed_unscored_session()

        spec = ChunkSpec(chunk_id=0, of_chunks=1, chunk_size=10, lookback_days=7)
        df = _fetch_features_dataframe(spec)

        assert df.empty, "INNER JOIN should drop sessions with no replay features"

    def test_eventless_session_is_excluded_even_with_features(self) -> None:
        # A session with no replay events can't be scored; it must be dropped at
        # the eligibility stage (not just by the join) so it never consumes the
        # chunk's LIMIT budget — even though a features row exists for it here.
        insert_session_replay_event(
            team_id=self.team.id,
            session_id=self.session_id,
            distinct_id=self.distinct_id,
            start=self.session_start,
            event_count=0,
        )
        self._seed_replay_features()

        spec = ChunkSpec(chunk_id=0, of_chunks=1, chunk_size=10, lookback_days=7)
        df = _fetch_features_dataframe(spec)
        assert df.empty

    def test_already_scored_session_is_excluded(self) -> None:
        insert_session_replay_event(
            team_id=self.team.id,
            session_id=self.session_id,
            distinct_id=self.distinct_id,
            start=self.session_start,
            surfacing_score=0.75,
        )
        self._seed_replay_features()

        spec = ChunkSpec(chunk_id=0, of_chunks=1, chunk_size=10, lookback_days=7)
        df = _fetch_features_dataframe(spec)
        assert df.empty

    def test_stale_features_outside_lookback_are_excluded(self) -> None:
        self._seed_unscored_session()
        sync_execute(
            "INSERT INTO writable_session_replay_features ("
            "  session_id, team_id, distinct_id, min_first_timestamp, max_last_timestamp, event_count"
            ") SELECT %(session_id)s, %(team_id)s, %(distinct_id)s, "
            "now64(6) - INTERVAL 30 DAY, now64(6) - INTERVAL 29 DAY, 100",
            {"session_id": self.session_id, "team_id": self.team.id, "distinct_id": self.distinct_id},
        )

        spec = ChunkSpec(chunk_id=0, of_chunks=1, chunk_size=10, lookback_days=7)
        df = _fetch_features_dataframe(spec)
        assert df.empty

    def test_hash_partitioning_respects_chunk_id(self) -> None:
        self._seed_unscored_session()
        self._seed_replay_features()

        matching_chunk = None
        for chunk_id in range(8):
            spec = ChunkSpec(chunk_id=chunk_id, of_chunks=8, chunk_size=10, lookback_days=7)
            if not _fetch_features_dataframe(spec).empty:
                matching_chunk = chunk_id
                break

        assert matching_chunk is not None, "session should land in exactly one hash bucket"

        for chunk_id in range(8):
            if chunk_id == matching_chunk:
                continue
            spec = ChunkSpec(chunk_id=chunk_id, of_chunks=8, chunk_size=10, lookback_days=7)
            assert _fetch_features_dataframe(spec).empty
