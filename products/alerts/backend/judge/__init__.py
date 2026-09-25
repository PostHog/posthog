"""The AI series judge: a product-owned scorer that is not a ``BaseDetector``.

Only the contract is re-exported here so importing the package stays light. The
implementation is ``products.alerts.backend.judge.llm.LLMSeriesJudge``.
"""

from products.alerts.backend.judge.contract import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    LLM_DETECTOR_UNAVAILABLE_ERROR_CODE,
    LLM_DETECTOR_UNAVAILABLE_MESSAGE,
    MAX_CONCURRENT_MODEL_CALLS,
    MAX_PROMPT_POINTS,
    AnomalyKind,
    JudgeAttribution,
    LLMDetectorError,
    LLMDetectorMisconfiguredError,
    LLMDetectorUnavailableError,
    SeriesContext,
    SeriesJudge,
    SeriesJudgment,
)

__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "LLM_DETECTOR_UNAVAILABLE_ERROR_CODE",
    "LLM_DETECTOR_UNAVAILABLE_MESSAGE",
    "MAX_CONCURRENT_MODEL_CALLS",
    "MAX_PROMPT_POINTS",
    "AnomalyKind",
    "JudgeAttribution",
    "LLMDetectorError",
    "LLMDetectorMisconfiguredError",
    "LLMDetectorUnavailableError",
    "SeriesContext",
    "SeriesJudge",
    "SeriesJudgment",
]
