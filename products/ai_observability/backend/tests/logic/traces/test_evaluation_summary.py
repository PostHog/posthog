from datetime import datetime, timedelta
from typing import Any

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.evaluation_result import EvaluationResult
from products.ai_observability.backend.logic.traces.evaluation_summary import EvaluationSummary, NodeEvaluationRollup

from .rows import T0, make_evaluation_result_row

OTHER_EVALUATION_ID = "0192f2a4-5c1e-7000-8000-000000000e02"


def result(
    uuid: str, *, target: str | None = "gen-1", at: datetime = T0, passed: bool = True, **overrides: Any
) -> EvaluationResult:
    row = make_evaluation_result_row(
        uuid=uuid, target_event_id=target, timestamp=at, result="true" if passed else "false", **overrides
    )
    return EvaluationResult.from_row(row, trace_id="trace-1", output_config={})


def counts(summary: EvaluationSummary) -> tuple[int, int, int]:
    return (summary.passed, summary.failed, summary.unrated)


@parameterized.expand(
    [
        (
            "a re-run",
            [result("result-2", at=T0 + timedelta(seconds=1), passed=False), result("result-1", at=T0)],
        ),
        (
            "a backfill stamped with the time of the step it grades",
            [
                result("live", at=T0 + timedelta(minutes=5)),
                result(
                    "backfill",
                    at=T0 + timedelta(seconds=1),
                    passed=False,
                    backfill_id="backfill-1",
                    start_time=(T0 + timedelta(days=20)).isoformat(),
                ),
            ],
        ),
    ]
)
def test_counts_the_latest_run_per_evaluation_and_node(_name: str, results: list[EvaluationResult]) -> None:
    summary = EvaluationSummary.from_results(results)

    assert counts(summary) == (0, 1, 0)
    assert summary.nodes == (NodeEvaluationRollup(node_id="gen-1", outcome="fail"),)


def test_the_same_evaluation_on_two_nodes_counts_twice() -> None:
    summary = EvaluationSummary.from_results([result("result-1", target="gen-1"), result("result-2", target="gen-2")])

    assert counts(summary) == (2, 0, 0)


@parameterized.expand(
    [
        ("the same name", "Answers the question", "Answers the question", 1),
        ("different names", "Answers the question", "Cites a source", 2),
    ]
)
def test_results_without_an_evaluation_id_are_grouped_by_name(
    _name: str, first: str, second: str, counted: int
) -> None:
    summary = EvaluationSummary.from_results(
        [
            result("result-1", evaluation_id=None, evaluation_name=first),
            result("result-2", evaluation_id=None, evaluation_name=second, at=T0 + timedelta(seconds=1)),
        ]
    )

    assert sum(counts(summary)) == counted


@parameterized.expand(
    [
        ("an inconclusive run", {"skipped": "true"}),
        (
            "an unrated result",
            {"evaluation_type": "sentiment", "result_type": "sentiment", "sentiment_label": "neutral"},
        ),
    ]
)
def test_results_without_a_pass_or_fail_count_as_unrated(_name: str, overrides: dict[str, Any]) -> None:
    summary = EvaluationSummary.from_results([result("result-1", **overrides)])

    assert counts(summary) == (0, 0, 1)
    assert summary.nodes == (NodeEvaluationRollup(node_id="gen-1", outcome="unrated"),)


def test_a_node_is_fail_if_any_evaluation_fails_then_pass_if_any_passes() -> None:
    summary = EvaluationSummary.from_results(
        [
            result("result-1", target="gen-b"),
            result("result-2", target="gen-b", evaluation_id=OTHER_EVALUATION_ID, skipped="true"),
            result("result-3", target="gen-a"),
            result("result-4", target="gen-a", evaluation_id=OTHER_EVALUATION_ID, passed=False),
        ]
    )

    assert summary.nodes == (
        NodeEvaluationRollup(node_id="gen-a", outcome="fail"),
        NodeEvaluationRollup(node_id="gen-b", outcome="pass"),
    )
