"""Deterministic scorers for the metric search eval. They read the scores the task computed."""

from typing import Any

from products.data_catalog.evals.metric_search_cases import CaseType
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

_SCORE_KEYS = ("recall", "correct_no_match", "sibling_ranked_above", "confident_when_present")


class MetricSearchScore(Scorer):
    """One of the per-case scores, averaged over every case it applies to."""

    def __init__(self, key: str) -> None:
        if key not in _SCORE_KEYS:
            raise ValueError(f"Unknown metric search score: {key}")
        self._key = key
        super().__init__()

    def _name(self) -> str:
        return f"metric_search_{self._key}"

    def _run_eval_sync(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        if not output or "scores" not in output:
            return Score(name=self._name(), score=0.0, metadata={"reason": output.get("error") if output else None})
        return Score(name=self._name(), score=output["scores"][self._key], metadata={"ranked": output["ranked"]})


class CaseTypeRecall(Scorer):
    """Recall over the cases of one type, so the scorecard shows which lane finds what."""

    def __init__(self, case_type: CaseType) -> None:
        self._case_type = case_type
        super().__init__()

    def _name(self) -> str:
        return f"metric_search_recall_{self._case_type.value}"

    def _run_eval_sync(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        if not output or output.get("case_type") != self._case_type.value:
            return Score(name=self._name(), score=None)
        if "scores" not in output:
            return Score(name=self._name(), score=0.0, metadata={"reason": output.get("error")})
        return Score(name=self._name(), score=output["scores"]["recall"], metadata={"ranked": output["ranked"]})


def metric_search_scorers() -> list[Scorer]:
    return [
        *(MetricSearchScore(key) for key in _SCORE_KEYS),
        *(CaseTypeRecall(case_type) for case_type in CaseType if case_type != CaseType.REAL_GAP),
    ]
