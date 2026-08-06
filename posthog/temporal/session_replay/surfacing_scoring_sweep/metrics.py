import typing

from django.conf import settings

from temporalio import activity
from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput, Interceptor

from posthog.temporal.ai_observability.metrics import ExecutionTimeRecorder, get_metric_meter

SCORE_CHUNK_ACTIVITY_TYPE = "score_chunk_activity"

SCORE_CHUNK_LATENCY_HISTOGRAM = "surfacing_scoring_score_chunk_activity_execution_latency"

SURFACING_SCORING_LATENCY_HISTOGRAM_METRICS = (SCORE_CHUNK_LATENCY_HISTOGRAM,)
SURFACING_SCORING_LATENCY_HISTOGRAM_BUCKETS = [
    1_000.0,  # 1 second
    5_000.0,  # 5 seconds
    10_000.0,  # 10 seconds
    30_000.0,  # 30 seconds
    60_000.0,  # 1 minute
    120_000.0,  # 2 minutes
    240_000.0,  # 4 minutes (SCORE_CHUNK_ACTIVITY_TIMEOUT)
]

TOTAL_FETCHED_COUNTER = "surfacing_scoring_total_fetched"
TOTAL_FETCHED_DESCRIPTION = "Sessions fetched from ClickHouse in a surfacing scoring sweep tick"

TOTAL_SCORED_COUNTER = "surfacing_scoring_total_scored"
TOTAL_SCORED_DESCRIPTION = "Sessions scored in a surfacing scoring sweep tick"

CHUNKS_FAILED_COUNTER = "surfacing_scoring_chunks_failed"
CHUNKS_FAILED_DESCRIPTION = "Hash-partitioned chunks that failed in a surfacing scoring sweep tick"

ESTIMATED_BACKLOG_GAUGE = "surfacing_scoring_estimated_backlog"
ESTIMATED_BACKLOG_DESCRIPTION = (
    "Estimated eligible-but-unscored session backlog (one hash bucket sampled, extrapolated)"
)


def record_backlog_estimate(estimated: int) -> None:
    # Gauge, not counter: it's a standing quantity, and 0 (caught up) is meaningful — emit unconditionally.
    get_metric_meter().create_gauge(ESTIMATED_BACKLOG_GAUGE, ESTIMATED_BACKLOG_DESCRIPTION).set(max(0, estimated))


def record_tick_summary(*, total_scored: int, total_fetched: int, chunks_failed: int) -> None:
    if total_scored <= 0 and total_fetched <= 0 and chunks_failed <= 0:
        return
    meter = get_metric_meter()
    if total_fetched > 0:
        meter.create_counter(TOTAL_FETCHED_COUNTER, TOTAL_FETCHED_DESCRIPTION).add(total_fetched)
    if total_scored > 0:
        meter.create_counter(TOTAL_SCORED_COUNTER, TOTAL_SCORED_DESCRIPTION).add(total_scored)
    if chunks_failed > 0:
        meter.create_counter(CHUNKS_FAILED_COUNTER, CHUNKS_FAILED_DESCRIPTION).add(chunks_failed)


class SurfacingScoringMetricsInterceptor(Interceptor):
    task_queue = settings.SURFACING_SCORING_SWEEP_TASK_QUEUE

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _SurfacingScoringActivityInterceptor(super().intercept_activity(next))


class _SurfacingScoringActivityInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> typing.Any:
        if activity.info().activity_type != SCORE_CHUNK_ACTIVITY_TYPE:
            return await super().execute_activity(input)
        with ExecutionTimeRecorder(
            SCORE_CHUNK_LATENCY_HISTOGRAM,
            description="Wall time for score_chunk_activity (fetch, predict, publish)",
        ):
            return await super().execute_activity(input)
