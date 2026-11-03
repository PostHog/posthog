from datetime import UTC, datetime

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from products.ai_observability.backend.facade import contracts
from products.ai_observability.backend.facade.api import (
    NoPassingRuleError,
    NoScoreScaleError,
    get_evaluation_runs,
    get_evaluation_score_distribution,
)
from products.ai_observability.backend.logic.evaluations.period import PeriodBounds
from products.ai_observability.backend.logic.evaluations.score_distribution import score_buckets
from products.ai_observability.backend.models.evaluations import Evaluation

PERIOD = PeriodBounds(start=datetime(2026, 3, 8, tzinfo=UTC), end=datetime(2026, 3, 11, tzinfo=UTC))


@parameterized.expand(
    [
        ("small integer scale", 1, 5, None, ("1", "2", "3", "4", "5")),
        ("zero to one", 0, 1, None, tuple(f"{index / 10:g}-{(index + 1) / 10:g}" for index in range(10))),
        ("whole step on a short scale", 0, 1, 1, ("0", "1")),
        ("fractional step", 1, 5, 0.5, tuple(f"{1 + index * 0.4:g}-{1 + (index + 1) * 0.4:g}" for index in range(10))),
        ("wide integer scale", 0, 100, None, tuple(f"{index * 10}-{(index + 1) * 10}" for index in range(10))),
    ]
)
def test_score_buckets(_name: str, low: float, high: float, step: float | None, labels: tuple[str, ...]) -> None:
    buckets = score_buckets(contracts.ScoreScale(min=low, max=high), step)
    assert buckets is not None and buckets.labels == labels


class TestEvaluationRunsAndScores(ClickhouseTestMixin, BaseTest):
    def _evaluation(self, output_type: str, output_config: dict) -> Evaluation:
        return Evaluation.objects.create(
            team=self.team,
            name=output_type,
            evaluation_type="hog",
            evaluation_config={"source": "return true"},
            output_type=output_type,
            output_config=output_config,
        )

    def _run(self, evaluation: Evaluation, timestamp: str, **properties: object) -> None:
        _create_event(
            team=self.team,
            event="$ai_evaluation",
            distinct_id="user-1",
            timestamp=timestamp,
            properties={"$ai_evaluation_id": str(evaluation.id), **properties},
        )

    def test_runs_and_score_distribution(self) -> None:
        judge = self._evaluation("boolean", {})
        relevance = self._evaluation(
            "numeric", {"min": 1, "max": 5, "passing_rule": {"operator": "gte", "threshold": 4}}
        )
        fraction = self._evaluation("numeric", {"min": 0, "max": 1})
        for hour in range(7):
            self._run(
                judge,
                f"2026-03-09T1{hour}:00:00Z",
                **{
                    "$ai_evaluation_result": False,
                    "$ai_evaluation_reasoning": "x" * 2000 if hour == 6 else f"reason {hour}",
                    "$ai_target_event_id": f"generation-{hour}",
                    "$ai_trace_id": f"trace-{hour}",
                },
            )
        self._run(judge, "2026-03-09T20:00:00Z", **{"$ai_evaluation_result": True, "$ai_trace_id": "trace-passed"})
        self._run(judge, "2026-03-09T21:00:00Z", **{"$ai_evaluation_result": False, "$ai_evaluation_skipped": True})
        self._run(judge, "2026-03-01T10:00:00Z", **{"$ai_evaluation_result": False})
        numeric = {"$ai_evaluation_result_type": "numeric"}
        for score in (1, 4, 4, 5, 4.4):
            self._run(relevance, "2026-03-09T10:00:00Z", **numeric, **{"$ai_evaluation_numeric_result": score})
        # Float division puts 0.3, 0.6 and 0.7 just under their bucket's lower edge.
        for score in (0.0, 0.3, 0.6, 0.7, 1.0):
            self._run(fraction, "2026-03-09T10:00:00Z", **numeric, **{"$ai_evaluation_numeric_result": score})
        flush_persons_and_events()

        failures = get_evaluation_runs(self.team, None, str(judge.id), PERIOD, "failed", 5).results
        assert [run.trace_id for run in failures] == ["trace-6", "trace-5", "trace-4", "trace-3", "trace-2"]
        assert {run.outcome for run in failures} == {"failed"}
        assert failures[0].reasoning == "x" * 999 + "…"
        assert failures[1].target_event_id == "generation-5"
        passed = get_evaluation_runs(self.team, None, str(judge.id), PERIOD, "passed", 5).results
        assert [(run.trace_id, run.outcome) for run in passed] == [("trace-passed", "passed")]
        # Without an outcome, the skipped run at 21:00 is left out.
        graded = get_evaluation_runs(self.team, None, str(judge.id), PERIOD, None, 2).results
        assert [run.outcome for run in graded] == ["passed", "failed"]
        relevance_failures = get_evaluation_runs(self.team, None, str(relevance.id), PERIOD, "failed", 5).results
        assert [run.timestamp.hour for run in relevance_failures] == [10]
        # An evaluation without a passing rule still lists its scored runs, with no outcome.
        scored = get_evaluation_runs(self.team, None, str(fraction.id), PERIOD, None, 50).results
        assert len(scored) == 5 and {run.outcome for run in scored} == {None}
        with pytest.raises(NoPassingRuleError):
            get_evaluation_runs(self.team, None, str(fraction.id), PERIOD, "failed", 5)

        assert get_evaluation_score_distribution(
            self.team, None, str(relevance.id), PERIOD
        ) == contracts.ScoreHistogram(
            scale=contracts.ScoreScale(min=1, max=5),
            buckets=[
                contracts.ScoreBucket(label=str(score), count=count)
                for score, count in zip(range(1, 6), [1, 0, 0, 3, 1])
            ],
        )
        histogram = get_evaluation_score_distribution(self.team, None, str(fraction.id), PERIOD)
        assert [bucket.count for bucket in histogram.buckets] == [1, 0, 0, 1, 0, 0, 1, 1, 0, 1]
        with pytest.raises(NoScoreScaleError):
            get_evaluation_score_distribution(self.team, None, str(judge.id), PERIOD)
