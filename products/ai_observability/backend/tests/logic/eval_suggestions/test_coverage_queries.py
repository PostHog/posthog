from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event

from django.utils import timezone

from products.ai_observability.backend.logic.eval_suggestions.coverage_queries import (
    EvaluationRunCounts,
    SharedReasoningRow,
    load_evaluation_runs,
    load_shared_reasoning,
)


class TestCoverageQueries(ClickhouseTestMixin, BaseTest):
    def _run(self, evaluation_id: str, properties: dict[str, Any]) -> None:
        _create_event(
            team=self.team,
            event="$ai_evaluation",
            distinct_id="user-1",
            timestamp=timezone.now() - timedelta(hours=1),
            properties={"$ai_evaluation_id": evaluation_id, **properties},
        )

    def test_runs_that_graded_nothing_are_not_counted(self) -> None:
        self._run("graded", {"$ai_evaluation_result": True})
        self._run("graded", {"$ai_evaluation_result": False})
        self._run("skipped", {"$ai_evaluation_skipped": "true"})
        self._run("not_applicable", {"$ai_evaluation_applicable": False})

        rows = load_evaluation_runs(
            self.team, ["graded", "skipped", "not_applicable"], timezone.now() - timedelta(days=30)
        )

        assert rows == [EvaluationRunCounts(evaluation_id="graded", runs=2, true_runs=1, false_runs=1)]

    def test_shared_reasoning_counts_runs_whose_text_also_explains_the_opposite_outcome(self) -> None:
        for result in (True, False, True):
            reasoning = "The answer cites its data correctly."
            self._run("shared", {"$ai_evaluation_result": result, "$ai_evaluation_reasoning": reasoning})
        for index, result in enumerate((True, False)):
            reasoning = f"Run {index}: the answer is {result}."
            self._run("distinct", {"$ai_evaluation_result": result, "$ai_evaluation_reasoning": reasoning})

        rows = load_shared_reasoning(self.team, ["shared", "distinct"], timezone.now() - timedelta(days=30))

        assert rows == [SharedReasoningRow(evaluation_id="shared", shared_runs=3)]
