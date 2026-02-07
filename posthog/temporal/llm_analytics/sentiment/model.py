"""Sentiment classification using cardiffnlp/twitter-roberta-base-sentiment-latest.

Uses ONNX Runtime for inference (~60MB) instead of PyTorch (~2GB).
Loads the model once per worker process (singleton) and provides a
classify() function that returns three-class sentiment scores.
"""

import threading
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

MODEL_NAME = "cardiffnlp/twitter-roberta-base-sentiment-latest"
LABELS = ["negative", "neutral", "positive"]

_model_lock = threading.Lock()
_pipeline = None


@dataclass
class SentimentResult:
    label: str
    score: float
    scores: dict[str, float]


def _load_pipeline():
    """Load the sentiment classification pipeline via ONNX Runtime. Called once per worker."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    with _model_lock:
        # Double-check after acquiring lock
        if _pipeline is not None:
            return _pipeline

        from optimum.onnxruntime import ORTModelForSequenceClassification
        from transformers import AutoTokenizer, pipeline

        logger.info("Loading sentiment model (ONNX)", model=MODEL_NAME)
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = ORTModelForSequenceClassification.from_pretrained(
            MODEL_NAME,
            export=True,
        )
        _pipeline = pipeline(
            "sentiment-analysis",
            model=model,
            tokenizer=tokenizer,
            top_k=None,  # Return all class scores
            truncation=True,
            max_length=512,
        )
        logger.info("Sentiment model loaded (ONNX)", model=MODEL_NAME)
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
