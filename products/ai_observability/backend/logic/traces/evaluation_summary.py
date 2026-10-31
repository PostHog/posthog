from collections import Counter, defaultdict
from collections.abc import Collection, Sequence
from typing import Self

from posthog.dataclasses import frozen

from ...facade.contracts import EvaluationOutcome, EvaluationRollupOutcome
from .evaluation_result import EvaluationResult

_ROLLUP_OUTCOMES: dict[EvaluationOutcome, EvaluationRollupOutcome] = {
    "pass": "pass",
    "fail": "fail",
    "inconclusive": "unrated",
    "unrated": "unrated",
}


@frozen
class _EvaluationOnNode:
    # Results from outside PostHog carry no evaluation id, so their name stands in for it.
    evaluation: str
    node_id: str

    @classmethod
    def from_result(cls, result: EvaluationResult) -> Self:
        return cls(evaluation=result.evaluation_id or result.name, node_id=result.target_node_id)


def _node_outcome(outcomes: Collection[EvaluationRollupOutcome]) -> EvaluationRollupOutcome:
    if "fail" in outcomes:
        return "fail"
    return "pass" if "pass" in outcomes else "unrated"


@frozen
class NodeEvaluationRollup:
    node_id: str
    outcome: EvaluationRollupOutcome


@frozen
class EvaluationSummary:
    """Counts the latest run of each evaluation on each node, so re-runs and backfills count once."""

    passed: int
    failed: int
    unrated: int
    nodes: tuple[NodeEvaluationRollup, ...]

    @classmethod
    def from_results(cls, results: Sequence[EvaluationResult]) -> Self:
        latest: dict[_EvaluationOnNode, EvaluationResult] = {}
        for result in results:
            key = _EvaluationOnNode.from_result(result)
            kept = latest.get(key)
            if kept is None or result.produced_at > kept.produced_at:
                latest[key] = result

        totals: Counter[EvaluationRollupOutcome] = Counter()
        by_node: defaultdict[str, set[EvaluationRollupOutcome]] = defaultdict(set)
        for result in latest.values():
            outcome = _ROLLUP_OUTCOMES[result.outcome]
            totals[outcome] += 1
            by_node[result.target_node_id].add(outcome)

        return cls(
            passed=totals["pass"],
            failed=totals["fail"],
            unrated=totals["unrated"],
            nodes=tuple(
                NodeEvaluationRollup(node_id=node_id, outcome=_node_outcome(outcomes))
                for node_id, outcomes in sorted(by_node.items())
            ),
        )
