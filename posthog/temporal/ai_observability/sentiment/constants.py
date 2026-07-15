"""Constants for sentiment classification."""

import os
from pathlib import Path


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        return default
    return max(1, value)


def _unit_float_env(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return min(max(value, 0.0), 1.0)


# Model
MODEL_NAME = "cardiffnlp/twitter-roberta-base-sentiment-latest"
MODEL_MAX_TOKENS = 512  # context window for the cardiffnlp model
LABELS = ["negative", "neutral", "positive"]
ONNX_CACHE_DIR = Path(os.environ.get("POSTHOG_SENTIMENT_MODEL_CACHE", "/tmp/posthog-sentiment-onnx-cache"))
ONNX_INTRA_OP_NUM_THREADS = _positive_int_env("POSTHOG_SENTIMENT_ONNX_INTRA_OP_NUM_THREADS", 1)
ONNX_INTER_OP_NUM_THREADS = _positive_int_env("POSTHOG_SENTIMENT_ONNX_INTER_OP_NUM_THREADS", 1)

# Extraction bounds
MAX_USER_MESSAGES = 50
MAX_MESSAGE_CHARS = 2000
SENTIMENT_EVAL_MAX_USER_MESSAGES = 1
SENTIMENT_EVAL_MAX_MESSAGE_CHARS = 1000
SENTIMENT_EVAL_MESSAGE_HEAD_CHARS = 300

# Calibration for non-conversational text.
# The cardiffnlp model is tweet-trained and over-labels terse, imperative
# product/admin requests (e.g. "remove website domain authorized URLs project
# settings") as negative. Fall back to neutral when the winning non-neutral label
# doesn't beat the neutral score by at least this margin, so low-confidence
# non-neutral labels don't read as real negatives.
SENTIMENT_NEUTRAL_MARGIN = _unit_float_env("POSTHOG_SENTIMENT_NEUTRAL_MARGIN", 0.15)

# Batch classification
CLASSIFY_BATCH_SIZE = 32  # texts per ONNX forward pass
