from __future__ import annotations

import pytest

from .judge import JudgeScorerError
from .runner import run_suite
from .types import EvalCase, EvalMetric, EvalSuite, MetricOutcome


class StubReporter:
    def __init__(self):
        self.analytics_client = object()
        self.events: list[dict] = []
        self.flushed = False

    def capture_evaluation(self, **kwargs) -> None:
        self.events.append(kwargs)

    def flush(self) -> None:
        self.flushed = True


@pytest.mark.asyncio
async def eval_run_suite_emits_one_event_per_metric() -> None:
    async def task(value: str) -> str:
        return value.upper()

    async def scorer(case, output, context) -> MetricOutcome:
        return MetricOutcome(status="ok", score=1.0, reasoning="ok", trace_id="judge-trace-1")

    suite = EvalSuite(
        experiment_name="demo",
        task=task,
        cases=[EvalCase(id="case-1", name="case", input="hello", expected="HELLO")],
        metrics=[
            EvalMetric(
                name="quality",
                version="1",
                result_type="numeric",
                score_min=0,
                score_max=1,
                scorer=scorer,
            )
        ],
    )
    reporter = StubReporter()

    results = await run_suite(suite, reporter, distinct_id="eval-run-1")

    assert len(results) == 1
    assert reporter.flushed is True
    assert reporter.events[0]["trace_id"] == "judge-trace-1"
    assert reporter.events[0]["output_text"] == "HELLO"


@pytest.mark.asyncio
async def eval_run_suite_preserves_trace_id_for_metric_failures() -> None:
    async def task(value: str) -> str:
        return value.upper()

    async def scorer(case, output, context) -> MetricOutcome:
        raise JudgeScorerError("judge returned invalid json", trace_id="judge-trace-error")

    suite = EvalSuite(
        experiment_name="demo",
        task=task,
        cases=[EvalCase(id="case-1", name="case", input="hello", expected="HELLO")],
        metrics=[
            EvalMetric(
                name="quality",
                version="1",
                result_type="numeric",
                score_min=0,
                score_max=1,
                scorer=scorer,
            )
        ],
    )
    reporter = StubReporter()

    with pytest.raises(RuntimeError, match="Metric quality failed"):
        await run_suite(suite, reporter, distinct_id="eval-run-1")

    assert reporter.flushed is True
    assert reporter.events[0]["status"] == "error"
    assert reporter.events[0]["trace_id"] == "judge-trace-error"
