from __future__ import annotations

from braintrust import Score
from braintrust_core.score import Scorer


class WeightedScorer(Scorer):
    """Combines multiple scorer results with configurable weights.

    Example::

        WeightedScorer(
            scorers=[TestsPass(), LintClean(), CodeQuality()],
            weights=[0.5, 0.2, 0.3],
        )
    """

    def __init__(self, *, scorers: list[Scorer], weights: list[float]):
        if len(scorers) != len(weights):
            raise ValueError(f"Number of scorers ({len(scorers)}) must match number of weights ({len(weights)})")
        if abs(sum(weights) - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {sum(weights)}")
        self.scorers = scorers
        self.weights = weights

    def _name(self) -> str:
        return "weighted_composite"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        sub_scores: list[Score] = []
        for scorer in self.scorers:
            score = await scorer._run_eval_async(output, expected, **kwargs)
            sub_scores.append(score)
        return self._combine(sub_scores)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        sub_scores: list[Score] = []
        for scorer in self.scorers:
            score = scorer._run_eval_sync(output, expected, **kwargs)
            sub_scores.append(score)
        return self._combine(sub_scores)

    def _combine(self, sub_scores: list[Score]) -> Score:
        weighted_sum = 0.0
        weight_sum = 0.0
        sub_results = {}

        for score, weight in zip(sub_scores, self.weights):
            sub_results[score.name] = {"score": score.score, "weight": weight}
            if score.score is not None:
                weighted_sum += score.score * weight
                weight_sum += weight

        final_score = weighted_sum / weight_sum if weight_sum > 0 else None

        return Score(
            name=self._name(),
            score=final_score,
            metadata={"sub_scores": sub_results},
        )


class PartialCreditScorer(Scorer):
    """Awards partial credit across independent sub-tasks.

    Each sub-scorer evaluates one component of the task independently.
    Final score = mean of all non-None sub-scores.

    Example::

        PartialCreditScorer(
            scorers=[
                FilesModified(),   # did it touch the right files?
                TestsPass(),       # do tests pass?
                ExitCodeZero(),    # did it exit cleanly?
            ],
        )
    """

    def __init__(self, *, scorers: list[Scorer]):
        self.scorers = scorers

    def _name(self) -> str:
        return "partial_credit"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        sub_scores: list[Score] = []
        for scorer in self.scorers:
            score = await scorer._run_eval_async(output, expected, **kwargs)
            sub_scores.append(score)
        return self._combine(sub_scores)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        sub_scores: list[Score] = []
        for scorer in self.scorers:
            score = scorer._run_eval_sync(output, expected, **kwargs)
            sub_scores.append(score)
        return self._combine(sub_scores)

    def _combine(self, sub_scores: list[Score]) -> Score:
        valid_scores = [s for s in sub_scores if s.score is not None]
        sub_results = {s.name: s.score for s in sub_scores}

        if not valid_scores:
            return Score(name=self._name(), score=None, metadata={"sub_scores": sub_results})

        mean_score = sum(s.score for s in valid_scores) / len(valid_scores)
        return Score(
            name=self._name(),
            score=mean_score,
            metadata={
                "sub_scores": sub_results,
                "components_scored": len(valid_scores),
                "components_total": len(sub_scores),
            },
        )
