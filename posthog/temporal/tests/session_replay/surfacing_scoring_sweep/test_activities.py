from __future__ import annotations

from datetime import datetime

import pytest
from unittest import mock

import numpy as np
import pandas as pd
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.temporal.session_replay.surfacing_scoring_sweep.activities import (
    _build_partial_row,
    list_chunks_activity,
    score_chunk_activity,
)
from posthog.temporal.session_replay.surfacing_scoring_sweep.constants import (
    CH_FEATURE_QUERY_TIMEOUT_S,
    DEFAULT_OF_CHUNKS,
    SCORE_CHUNK_HEARTBEAT_TIMEOUT,
    TARGET_CHUNK_SIZE,
)
from posthog.temporal.session_replay.surfacing_scoring_sweep.features import FeatureValidationError
from posthog.temporal.session_replay.surfacing_scoring_sweep.types import ChunkSpec, ScoreSessionsBatchInputs

ACTIVITIES_MODULE = "posthog.temporal.session_replay.surfacing_scoring_sweep.activities"


class TestListChunksActivity:
    @pytest.mark.asyncio
    async def test_always_dispatches_all_hash_buckets(self) -> None:
        with mock.patch(f"{ACTIVITIES_MODULE}._count_unscored_in_one_bucket", return_value=0):
            result = await ActivityEnvironment().run(list_chunks_activity, ScoreSessionsBatchInputs())

        assert len(result.chunks) == DEFAULT_OF_CHUNKS
        assert result.estimated_unscored_sessions == 0
        assert {spec.chunk_id for spec in result.chunks} == set(range(DEFAULT_OF_CHUNKS))
        for spec in result.chunks:
            assert spec.of_chunks == DEFAULT_OF_CHUNKS
            assert spec.chunk_size == TARGET_CHUNK_SIZE

    @pytest.mark.asyncio
    async def test_extrapolates_backlog_estimate_from_bucket_zero_sample(self) -> None:
        with mock.patch(f"{ACTIVITIES_MODULE}._count_unscored_in_one_bucket", return_value=42):
            result = await ActivityEnvironment().run(list_chunks_activity, ScoreSessionsBatchInputs())

        assert result.estimated_unscored_sessions == 42 * DEFAULT_OF_CHUNKS


class TestBuildPartialRow:
    def test_naive_datetime_is_treated_as_utc(self) -> None:
        naive = datetime(2026, 5, 7, 10, 0, 0)
        row = _build_partial_row(
            team_id=1,
            session_id="sess",
            distinct_id="user",
            min_first_timestamp=naive,
            score=0.5,
        )
        assert row["first_timestamp"] == "2026-05-07 10:00:00.000001"
        assert row["last_timestamp"] == "2026-05-07 10:00:00.000001"


class TestScoreChunkActivity:
    @pytest.mark.asyncio
    async def test_empty_chunk_returns_zero_without_touching_model(self, surfacing_booster_path: object) -> None:
        spec = ChunkSpec(chunk_id=0, of_chunks=1, chunk_size=10, lookback_days=7)
        empty = pd.DataFrame(columns=pd.Index(["team_id", "session_id", "distinct_id", "min_first_timestamp"]))

        with (
            mock.patch(f"{ACTIVITIES_MODULE}._fetch_features_dataframe", return_value=empty),
            mock.patch(f"{ACTIVITIES_MODULE}.get_feature_names") as get_names_mock,
            mock.patch(f"{ACTIVITIES_MODULE}.predict") as predict_mock,
        ):
            result = await ActivityEnvironment().run(score_chunk_activity, spec)

        assert result.scored == 0
        get_names_mock.assert_not_called()
        predict_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_feature_validation_error_is_non_retryable(self, surfacing_booster_path: object) -> None:
        spec = ChunkSpec(chunk_id=0, of_chunks=1, chunk_size=10, lookback_days=7)
        df = pd.DataFrame({"team_id": [1], "session_id": ["s"], "distinct_id": ["d"], "event_rate": [0.1]})

        with (
            mock.patch(f"{ACTIVITIES_MODULE}._fetch_features_dataframe", return_value=df),
            mock.patch(f"{ACTIVITIES_MODULE}.get_feature_names", return_value=("event_rate", "click_rate")),
            mock.patch(
                f"{ACTIVITIES_MODULE}.validate_features",
                side_effect=FeatureValidationError("missing columns"),
            ),
        ):
            with pytest.raises(ApplicationError) as exc_info:
                await ActivityEnvironment().run(score_chunk_activity, spec)

        assert exc_info.value.non_retryable is True
        assert exc_info.value.type == "FeatureValidationError"

    @pytest.mark.asyncio
    async def test_happy_path_scores_and_publishes(self, surfacing_booster_path: object) -> None:
        spec = ChunkSpec(chunk_id=0, of_chunks=1, chunk_size=10, lookback_days=7)
        feature_names = ("event_rate",)
        df = pd.DataFrame(
            {
                "team_id": [1],
                "session_id": ["sess-1"],
                "distinct_id": ["user-1"],
                "min_first_timestamp": pd.to_datetime(["2026-05-07 10:00:00+00:00"]),
                "event_rate": [0.2],
            }
        )

        with (
            mock.patch(f"{ACTIVITIES_MODULE}._fetch_features_dataframe", return_value=df),
            mock.patch(f"{ACTIVITIES_MODULE}.get_feature_names", return_value=feature_names),
            mock.patch(f"{ACTIVITIES_MODULE}.validate_features"),
            mock.patch(f"{ACTIVITIES_MODULE}.predict", return_value=np.array([0.42], dtype=np.float32)),
            mock.patch(f"{ACTIVITIES_MODULE}._publish_scores", return_value=1) as publish_mock,
        ):
            result = await ActivityEnvironment().run(score_chunk_activity, spec)

        assert result.scored == 1
        publish_mock.assert_called_once()


class TestPipelineTimeouts:
    def test_heartbeat_timeout_exceeds_clickhouse_query_timeout(self) -> None:
        assert SCORE_CHUNK_HEARTBEAT_TIMEOUT.total_seconds() > CH_FEATURE_QUERY_TIMEOUT_S
