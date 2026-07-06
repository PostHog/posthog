from __future__ import annotations

from datetime import datetime

import pytest
from unittest import mock

import numpy as np
import pandas as pd
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.temporal.session_replay.surfacing_scoring_sweep.activities import (
    _build_features_dataframe,
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
from posthog.temporal.session_replay.surfacing_scoring_sweep.features import (
    ID_COLUMNS,
    FeatureValidationError,
    validate_features,
)
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

    @pytest.mark.asyncio
    async def test_emits_backlog_gauge_with_extrapolated_estimate(self) -> None:
        with (
            mock.patch(f"{ACTIVITIES_MODULE}._count_unscored_in_one_bucket", return_value=42),
            mock.patch(f"{ACTIVITIES_MODULE}.record_backlog_estimate") as record_backlog_mock,
        ):
            await ActivityEnvironment().run(list_chunks_activity, ScoreSessionsBatchInputs())

        record_backlog_mock.assert_called_once_with(42 * DEFAULT_OF_CHUNKS)


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


class TestBuildFeaturesDataframe:
    def _rows(self, feature_names: tuple[str, ...], null_feature: str | None) -> tuple[list[tuple], list[str]]:
        columns = [*ID_COLUMNS, *feature_names]
        rows = [
            (
                1,
                f"sess-{i}",
                f"user-{i}",
                datetime(2026, 5, 7, 10, 0, 0),
                *(None if name == null_feature else 0.1 for name in feature_names),
            )
            for i in range(2)
        ]
        return rows, columns

    def test_all_null_feature_column_is_coerced_to_float_and_validates(
        self, feature_names_for_tests: tuple[str, ...]
    ) -> None:
        # Reproduces the production failure: a `x / nullIf(denom, 0)` feature is
        # NULL for every row in a chunk of simple sessions. The driver returns
        # all-None, which pandas infers as object dtype unless we coerce.
        rows, columns = self._rows(feature_names_for_tests, null_feature="inter_action_gap_mean_ms")

        df = _build_features_dataframe(rows, columns)

        assert df["inter_action_gap_mean_ms"].dtype.kind == "f"
        assert df["inter_action_gap_mean_ms"].isna().all()
        validate_features(df, feature_names=feature_names_for_tests)

    def test_id_columns_keep_native_dtypes(self, feature_names_for_tests: tuple[str, ...]) -> None:
        rows, columns = self._rows(feature_names_for_tests, null_feature=None)

        df = _build_features_dataframe(rows, columns)

        assert df["session_id"].dtype.kind == "O"
        assert df["min_first_timestamp"].dtype.kind == "M"

    def test_non_numeric_feature_drift_is_left_for_validation_to_reject(
        self, feature_names_for_tests: tuple[str, ...]
    ) -> None:
        # Coercion only touches all-NULL columns, so genuine SQL drift (a typed
        # non-numeric column) stays object dtype and fails loudly at the validator
        # — a non-retryable FeatureValidationError, not a silently coerced NaN.
        rows, columns = self._rows(feature_names_for_tests, null_feature=None)
        bad = list(rows[0])
        bad[len(ID_COLUMNS)] = "not-a-number"  # first feature column

        df = _build_features_dataframe([tuple(bad)], columns)

        assert df[feature_names_for_tests[0]].dtype.kind == "O"
        with pytest.raises(FeatureValidationError):
            validate_features(df, feature_names=feature_names_for_tests)


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

    @pytest.mark.asyncio
    async def test_out_of_contract_row_is_dropped_not_chunk_blocking(self, surfacing_booster_path: object) -> None:
        spec = ChunkSpec(chunk_id=0, of_chunks=1, chunk_size=10, lookback_days=7)
        feature_names = ("event_rate",)
        df = pd.DataFrame(
            {
                "team_id": [1, 1],
                "session_id": ["sess-bad", "sess-good"],
                "distinct_id": ["user-1", "user-2"],
                "min_first_timestamp": pd.to_datetime(["2026-05-07 10:00:00+00:00", "2026-05-07 11:00:00+00:00"]),
                "event_rate": [-1.0, 0.2],
            }
        )

        with (
            mock.patch(f"{ACTIVITIES_MODULE}._fetch_features_dataframe", return_value=df),
            mock.patch(f"{ACTIVITIES_MODULE}.get_feature_names", return_value=feature_names),
            mock.patch(f"{ACTIVITIES_MODULE}.predict", return_value=np.array([0.42], dtype=np.float32)),
            mock.patch(f"{ACTIVITIES_MODULE}._publish_scores", return_value=1) as publish_mock,
        ):
            result = await ActivityEnvironment().run(score_chunk_activity, spec)

        assert result.scored == 1
        published_df = publish_mock.call_args.args[0]
        assert published_df["session_id"].tolist() == ["sess-good"]

    @pytest.mark.asyncio
    async def test_all_rows_out_of_contract_returns_zero_scored(self, surfacing_booster_path: object) -> None:
        spec = ChunkSpec(chunk_id=0, of_chunks=1, chunk_size=10, lookback_days=7)
        feature_names = ("event_rate",)
        df = pd.DataFrame(
            {
                "team_id": [1],
                "session_id": ["sess-bad"],
                "distinct_id": ["user-1"],
                "min_first_timestamp": pd.to_datetime(["2026-05-07 10:00:00+00:00"]),
                "event_rate": [float("inf")],
            }
        )

        with (
            mock.patch(f"{ACTIVITIES_MODULE}._fetch_features_dataframe", return_value=df),
            mock.patch(f"{ACTIVITIES_MODULE}.get_feature_names", return_value=feature_names),
            mock.patch(f"{ACTIVITIES_MODULE}.predict") as predict_mock,
            mock.patch(f"{ACTIVITIES_MODULE}._publish_scores") as publish_mock,
        ):
            result = await ActivityEnvironment().run(score_chunk_activity, spec)

        assert result.scored == 0
        predict_mock.assert_not_called()
        publish_mock.assert_not_called()


class TestPipelineTimeouts:
    def test_heartbeat_timeout_exceeds_clickhouse_query_timeout(self) -> None:
        assert SCORE_CHUNK_HEARTBEAT_TIMEOUT.total_seconds() > CH_FEATURE_QUERY_TIMEOUT_S
