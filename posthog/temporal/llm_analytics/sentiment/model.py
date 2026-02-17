"""Sentiment classification using cardiffnlp/twitter-roberta-base-sentiment-latest.

Uses ONNX Runtime for inference (~60MB) instead of PyTorch (~2GB).
Loads the model once per worker process (singleton) and provides a
classify() function that returns three-class sentiment scores.

The ONNX export is cached to disk so subsequent worker restarts skip
the expensive PyTorch→ONNX conversion (~10s).
"""

import threading
from dataclasses import dataclass
from typing import Any

import structlog

from posthog.temporal.llm_analytics.sentiment.constants import CLASSIFY_BATCH_SIZE, LABELS, MODEL_NAME, ONNX_CACHE_DIR

logger = structlog.get_logger(__name__)

_model_lock = threading.Lock()
_pipeline_cache: dict[str, Any] = {}


@dataclass
class SentimentResult:
    label: str
    score: float
    scores: dict[str, float]


def _load_pipeline():
    """Load the sentiment classification pipeline via ONNX Runtime. Called once per worker.

    Uses a threading.Lock to ensure only one thread performs the export.
    The torch ONNX exporter is not thread-safe, so concurrent threads
    must wait rather than export in parallel.
    """
    if "pipe" in _pipeline_cache:
        return _pipeline_cache["pipe"]

    with _model_lock:
        if "pipe" in _pipeline_cache:
            return _pipeline_cache["pipe"]

        from optimum.onnxruntime import ORTModelForSequenceClassification
        from transformers import AutoTokenizer, pipeline

        cache_dir = str(ONNX_CACHE_DIR)
        onnx_cached = (ONNX_CACHE_DIR / "model.onnx").exists()

        try:
            if onnx_cached:
                logger.info("Loading sentiment model from ONNX cache", cache_dir=cache_dir)
                tokenizer = AutoTokenizer.from_pretrained(cache_dir)
                model = ORTModelForSequenceClassification.from_pretrained(cache_dir)
            else:
                logger.info("Exporting sentiment model to ONNX (first run)", model=MODEL_NAME)
                tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
                # PyTorch 2.9+ defaults torch.onnx.export to dynamo=True.
                # Optimum 1.25 does not override this, and the dynamo path can
                # emit external data files into temp dirs that disappear before
                # ORTModel loads them.
                import torch

                original_export = torch.onnx.export

                def export_with_dynamo_disabled(*args: Any, **kwargs: Any):
                    kwargs.setdefault("dynamo", False)
                    return original_export(*args, **kwargs)

                torch.onnx.export = export_with_dynamo_disabled
                try:
                    model = ORTModelForSequenceClassification.from_pretrained(MODEL_NAME, export=True)
                finally:
                    torch.onnx.export = original_export
                ONNX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                model.save_pretrained(cache_dir)
                tokenizer.save_pretrained(cache_dir)
                logger.info("ONNX model cached to disk", cache_dir=cache_dir)

            _pipeline_cache["pipe"] = pipeline(
                "sentiment-analysis",
                model=model,
                tokenizer=tokenizer,
                top_k=None,  # Return all class scores
                truncation=True,
                max_length=512,
            )
        except Exception:
            logger.exception("Failed to load sentiment model")
            raise

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


def classify_batch(texts: list[str]) -> list[SentimentResult]:
    """Classify a batch of texts. The pipeline handles internal chunking."""
    if not texts:
        return []

    pipe = _load_pipeline()
    # Pipeline with top_k=None returns list of list[dict] for batch input
    batch_results = pipe(texts, batch_size=CLASSIFY_BATCH_SIZE)
    return [_parse_single_result(result) for result in batch_results]


def classify(text: str) -> SentimentResult:
    """Classify a single text. Delegates to classify_batch."""
    return classify_batch([text])[0]
