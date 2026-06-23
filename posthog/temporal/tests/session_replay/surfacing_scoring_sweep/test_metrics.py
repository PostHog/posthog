import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings

from parameterized import parameterized
from temporalio.worker import ExecuteActivityInput

from posthog.temporal.common.worker import ALL_INTERCEPTOR_CLASSES
from posthog.temporal.session_replay.surfacing_scoring_sweep.activities import (
    list_chunks_activity,
    score_chunk_activity,
)
from posthog.temporal.session_replay.surfacing_scoring_sweep.constants import SCORE_CHUNK_ACTIVITY_TIMEOUT
from posthog.temporal.session_replay.surfacing_scoring_sweep.metrics import (
    CHUNKS_FAILED_COUNTER,
    CHUNKS_FAILED_DESCRIPTION,
    SCORE_CHUNK_ACTIVITY_TYPE,
    SCORE_CHUNK_LATENCY_HISTOGRAM,
    SURFACING_SCORING_LATENCY_HISTOGRAM_BUCKETS,
    SURFACING_SCORING_LATENCY_HISTOGRAM_METRICS,
    TOTAL_FETCHED_COUNTER,
    TOTAL_FETCHED_DESCRIPTION,
    TOTAL_SCORED_COUNTER,
    TOTAL_SCORED_DESCRIPTION,
    SurfacingScoringMetricsInterceptor,
    record_tick_summary,
)


class TestHistogramConfig:
    def test_latency_histogram_metric_names(self) -> None:
        assert SURFACING_SCORING_LATENCY_HISTOGRAM_METRICS == (SCORE_CHUNK_LATENCY_HISTOGRAM,)

    def test_latency_buckets_include_activity_timeout(self) -> None:
        timeout_ms = SCORE_CHUNK_ACTIVITY_TIMEOUT.total_seconds() * 1_000
        assert timeout_ms in SURFACING_SCORING_LATENCY_HISTOGRAM_BUCKETS
        assert SURFACING_SCORING_LATENCY_HISTOGRAM_BUCKETS == sorted(SURFACING_SCORING_LATENCY_HISTOGRAM_BUCKETS)

    def test_interceptor_registered_on_worker(self) -> None:
        assert SurfacingScoringMetricsInterceptor in ALL_INTERCEPTOR_CLASSES


class TestActivityTypeAlignment:
    def test_score_chunk_activity_type_matches_defn(self) -> None:
        assert SCORE_CHUNK_ACTIVITY_TYPE == score_chunk_activity.__name__

    def test_list_chunks_activity_is_not_timed(self) -> None:
        assert list_chunks_activity.__name__ != SCORE_CHUNK_ACTIVITY_TYPE


class TestSurfacingScoringMetricsInterceptor:
    def test_task_queue_matches_settings(self) -> None:
        assert SurfacingScoringMetricsInterceptor.task_queue == settings.SURFACING_SCORING_SWEEP_TASK_QUEUE

    def test_creates_activity_interceptor(self) -> None:
        interceptor = SurfacingScoringMetricsInterceptor()
        result = interceptor.intercept_activity(MagicMock())
        assert result is not None


class TestRecordTickSummary:
    @parameterized.expand(
        [
            ("fetched", 0, 99, 0, TOTAL_FETCHED_COUNTER, TOTAL_FETCHED_DESCRIPTION, 99),
            ("scored", 42, 0, 0, TOTAL_SCORED_COUNTER, TOTAL_SCORED_DESCRIPTION, 42),
            ("failed", 0, 0, 3, CHUNKS_FAILED_COUNTER, CHUNKS_FAILED_DESCRIPTION, 3),
        ]
    )
    def test_emits_counter(
        self,
        _name: str,
        total_scored: int,
        total_fetched: int,
        chunks_failed: int,
        counter_name: str,
        counter_description: str,
        expected_count: int,
    ) -> None:
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter

        with patch(
            "posthog.temporal.session_replay.surfacing_scoring_sweep.metrics.get_metric_meter",
            return_value=mock_meter,
        ):
            record_tick_summary(total_scored=total_scored, total_fetched=total_fetched, chunks_failed=chunks_failed)

        mock_meter.create_counter.assert_called_once_with(counter_name, counter_description)
        mock_counter.add.assert_called_once_with(expected_count)

    def test_emits_all_counters(self) -> None:
        mock_meter = MagicMock()
        with patch(
            "posthog.temporal.session_replay.surfacing_scoring_sweep.metrics.get_metric_meter",
            return_value=mock_meter,
        ):
            record_tick_summary(total_scored=10, total_fetched=100, chunks_failed=2)

        names = [call.args[0] for call in mock_meter.create_counter.call_args_list]
        assert names == [TOTAL_FETCHED_COUNTER, TOTAL_SCORED_COUNTER, CHUNKS_FAILED_COUNTER]

    @parameterized.expand(
        [
            ("all_zero", 0, 0, 0),
            ("negative_scored", -1, 0, 0),
            ("negative_fetched", 0, -1, 0),
            ("negative_failed", 0, 0, -1),
            ("all_negative", -5, -3, -2),
        ]
    )
    def test_noops_for_non_positive_counts(
        self, _name: str, total_scored: int, total_fetched: int, chunks_failed: int
    ) -> None:
        with patch(
            "posthog.temporal.session_replay.surfacing_scoring_sweep.metrics.get_metric_meter",
        ) as mock_get_meter:
            record_tick_summary(total_scored=total_scored, total_fetched=total_fetched, chunks_failed=chunks_failed)
            mock_get_meter.assert_not_called()

    @parameterized.expand(
        [
            ("only_fetched", -1, 5, 0, TOTAL_FETCHED_COUNTER, TOTAL_FETCHED_DESCRIPTION, 5),
            ("only_failed", 0, -1, 2, CHUNKS_FAILED_COUNTER, CHUNKS_FAILED_DESCRIPTION, 2),
            ("only_scored", 7, -1, 0, TOTAL_SCORED_COUNTER, TOTAL_SCORED_DESCRIPTION, 7),
        ]
    )
    def test_emits_only_positive_dimension(
        self,
        _name: str,
        total_scored: int,
        total_fetched: int,
        chunks_failed: int,
        counter_name: str,
        counter_description: str,
        expected_count: int,
    ) -> None:
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter

        with patch(
            "posthog.temporal.session_replay.surfacing_scoring_sweep.metrics.get_metric_meter",
            return_value=mock_meter,
        ):
            record_tick_summary(total_scored=total_scored, total_fetched=total_fetched, chunks_failed=chunks_failed)

        mock_meter.create_counter.assert_called_once_with(counter_name, counter_description)
        mock_counter.add.assert_called_once_with(expected_count)


@pytest.mark.asyncio
class TestSurfacingScoringActivityInterceptor:
    async def _run_interceptor(
        self,
        *,
        activity_type: str,
    ) -> tuple[AsyncMock, MagicMock]:
        next_interceptor = AsyncMock()
        next_interceptor.execute_activity.return_value = {"ok": True}
        interceptor = SurfacingScoringMetricsInterceptor().intercept_activity(next_interceptor)
        mock_input = MagicMock(spec=ExecuteActivityInput)

        with (
            patch(
                "posthog.temporal.session_replay.surfacing_scoring_sweep.metrics.activity.info",
                return_value=MagicMock(activity_type=activity_type),
            ),
            patch(
                "posthog.temporal.session_replay.surfacing_scoring_sweep.metrics.ExecutionTimeRecorder",
            ) as mock_recorder,
        ):
            mock_recorder.return_value.__enter__ = MagicMock(return_value=mock_recorder.return_value)
            mock_recorder.return_value.__exit__ = MagicMock(return_value=False)
            result = await interceptor.execute_activity(mock_input)

        assert result == {"ok": True}
        next_interceptor.execute_activity.assert_called_once_with(mock_input)
        return next_interceptor, mock_recorder

    async def test_records_latency_for_score_chunk_activity(self) -> None:
        _, mock_recorder = await self._run_interceptor(activity_type=SCORE_CHUNK_ACTIVITY_TYPE)
        mock_recorder.assert_called_once_with(
            SCORE_CHUNK_LATENCY_HISTOGRAM,
            description="Wall time for score_chunk_activity (fetch, predict, publish)",
        )

    async def test_skips_latency_for_list_chunks_activity(self) -> None:
        _, mock_recorder = await self._run_interceptor(activity_type=list_chunks_activity.__name__)
        mock_recorder.assert_not_called()

    async def test_records_latency_even_when_activity_raises(self) -> None:
        next_interceptor = AsyncMock()
        next_interceptor.execute_activity.side_effect = RuntimeError("chunk blew up")
        interceptor = SurfacingScoringMetricsInterceptor().intercept_activity(next_interceptor)
        mock_input = MagicMock(spec=ExecuteActivityInput)

        with (
            patch(
                "posthog.temporal.session_replay.surfacing_scoring_sweep.metrics.activity.info",
                return_value=MagicMock(activity_type=SCORE_CHUNK_ACTIVITY_TYPE),
            ),
            patch(
                "posthog.temporal.session_replay.surfacing_scoring_sweep.metrics.ExecutionTimeRecorder",
            ) as mock_recorder,
        ):
            mock_recorder.return_value.__enter__ = MagicMock(return_value=mock_recorder.return_value)
            mock_recorder.return_value.__exit__ = MagicMock(return_value=False)

            with pytest.raises(RuntimeError, match="chunk blew up"):
                await interceptor.execute_activity(mock_input)

        mock_recorder.assert_called_once()
