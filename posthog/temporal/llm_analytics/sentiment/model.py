"""Sentiment classification using cardiffnlp/twitter-roberta-base-sentiment-latest.

Uses ONNX Runtime for inference (~60MB) instead of PyTorch (~2GB).
Loads the pre-baked ONNX model once per worker process (singleton)
and provides a classify function that returns three-class
sentiment scores.

The ONNX model is baked into the Docker image at build time
(see Dockerfile.llm-analytics). The worker expects it at ONNX_CACHE_DIR.
"""

import threading
from typing import Any

import structlog

from posthog.temporal.llm_analytics.sentiment.constants import (
    CLASSIFY_BATCH_SIZE,
    LABELS,
    MODEL_MAX_TOKENS,
    MODEL_NAME,
    ONNX_CACHE_DIR,
)
from posthog.temporal.llm_analytics.sentiment.schema import SentimentResult

logger = structlog.get_logger(__name__)

_model_lock = threading.Lock()
_pipeline_cache: dict[str, Any] = {}


def _load_pipeline():
    """Load the pre-baked ONNX sentiment pipeline. Called once per worker.

    Uses double-checked locking to ensure only one thread loads the model.
    Raises FileNotFoundError if the ONNX model is missing from the expected
    cache directory — this means the Docker image was not built correctly.
    """
    if "pipe" in _pipeline_cache:
        return _pipeline_cache["pipe"]

    with _model_lock:
        if "pipe" in _pipeline_cache:
            return _pipeline_cache["pipe"]

        cache_dir = str(ONNX_CACHE_DIR)
        onnx_path = ONNX_CACHE_DIR / "model.onnx"

        if not onnx_path.exists():
            logger.error(
                "ONNX model not found — the Docker image must bake the model at build time",
                expected_path=str(onnx_path),
                cache_dir=cache_dir,
            )
            raise FileNotFoundError(
                f"Sentiment ONNX model not found at {onnx_path}. "
                f"Ensure Dockerfile.llm-analytics bakes the model into {ONNX_CACHE_DIR}."
            )

        from optimum.onnxruntime import ORTModelForSequenceClassification
        from transformers import AutoTokenizer, pipeline

        logger.info("Loading sentiment model from ONNX cache", cache_dir=cache_dir)
        tokenizer = AutoTokenizer.from_pretrained(cache_dir)
        model = ORTModelForSequenceClassification.from_pretrained(cache_dir)

        _pipeline_cache["pipe"] = pipeline(
            "sentiment-analysis",
            model=model,
            tokenizer=tokenizer,
            top_k=None,
            truncation=True,
            max_length=MODEL_MAX_TOKENS,
        )

        logger.info("Sentiment model loaded", model=MODEL_NAME)
        return _pipeline_cache["pipe"]


def _parse_single_result(scores_list: list[dict[str, Any]]) -> SentimentResult:
    """Convert a pipeline output for one text into a SentimentResult."""
    scores: dict[str, float] = {}
    for item in scores_list:
        scores[item["label"]] = round(item["score"], 4)

    for label in LABELS:
        if label not in scores:
            scores[label] = 0.0

    top_label = max(scores, key=scores.get)  # type: ignore
    return SentimentResult(label=top_label, score=scores[top_label], scores=scores)


def classify(texts: list[str]) -> list[SentimentResult]:
    """Classify a batch of texts. The pipeline handles internal chunking."""
    if not texts:
        return []

    pipe = _load_pipeline()
    # Pipeline with top_k=None returns list of list[dict] for batch input
    batch_results = pipe(texts, batch_size=CLASSIFY_BATCH_SIZE)
    return [_parse_single_result(result) for result in batch_results]
