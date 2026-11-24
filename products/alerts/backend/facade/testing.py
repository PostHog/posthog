"""Test-support facade for alerts.

Suites outside this product fake the AI judge's model through here instead of importing the judge internals.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from unittest.mock import patch

from products.alerts.backend.judge.contract import AnomalyKind
from products.alerts.backend.judge.llm import LLM_DETECTOR_DEFAULT_MODEL, LLM_DETECTOR_MODELS
from products.alerts.backend.judge.verdict import LLMDetectionVerdict

__all__ = ["fake_judge_model"]


@contextmanager
def fake_judge_model(*, is_anomaly: bool, rationale: str, kind: AnomalyKind = "none") -> Iterator[list[Any]]:
    """Answer every call to the judge's default model with one verdict, and record each request it was sent.

    A request carries the `model`, `ai_product`, `team_id` and `extra_headers` that the gateway would read.
    """
    requests: list[Any] = []
    verdict = LLMDetectionVerdict(rationale=rationale, is_anomaly=is_anomaly, kind=kind)

    def ask(request: Any) -> LLMDetectionVerdict:
        requests.append(request)
        return verdict

    with (
        patch("products.alerts.backend.judge.prompt.render_series_chart", return_value=None),
        patch("ee.hogai.utils.feature_flags.is_privacy_mode_enabled", return_value=False),
        patch.dict(LLM_DETECTOR_MODELS, {LLM_DETECTOR_DEFAULT_MODEL.value: ask}),
    ):
        yield requests
