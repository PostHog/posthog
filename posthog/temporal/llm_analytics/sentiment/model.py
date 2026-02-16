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

from posthog.temporal.llm_analytics.sentiment.constants import LABELS, MODEL_NAME, ONNX_CACHE_DIR

logger = structlog.get_logger(__name__)

_model_lock = threading.Lock()
_pipeline = None


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
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    with _model_lock:
        # Double-check after acquiring lock
        if _pipeline is not None:
            return _pipeline

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

            _pipeline = pipeline(
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
        return _pipeline


def classify(text: str) -> SentimentResult:
    """Classify text sentiment. Returns label, top score, and all scores.

    The model returns scores for three classes: negative, neutral, positive.
    """
    pipe = _load_pipeline()
    results = pipe(text)

    # results is [[{"label": "positive", "score": 0.87}, ...]]
    scores_list = results[0] if results else []

    scores = {}
    for item in scores_list:
        scores[item["label"]] = round(item["score"], 4)

    # Ensure all labels present
    for label in LABELS:
        if label not in scores:
            scores[label] = 0.0

    # Find top label
    top_label = max(scores, key=scores.get)  # type: ignore
    top_score = scores[top_label]

    return SentimentResult(
        label=top_label,
        score=top_score,
        scores=scores,
    )
